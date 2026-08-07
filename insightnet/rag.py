"""Retrieval index behind the "Ask InsightNet" assistant.

This module is deliberately shared between the offline builder (``insightnet-rag``)
and the online service. Both call the same ``search`` path, so the ranking you tune
with ``insightnet-rag --query`` is the ranking visitors get — there is no second
implementation to drift out of step.

Two properties of the corpus shape everything here:

* Researcher prose is generic. Every researcher now carries a short bio, but they run
  about 160 characters of institutional summary and draw on a vocabulary of only ~770
  distinct words. They describe domains, not the topics people search for: across all
  471 bios, "ERGM" appears 0 times, "Ebola" once and "Bayesian" once, against 3, 54 and
  49 occurrences in publication titles. So ``_researcher_chunk`` synthesizes a record
  from the topics and titles of that person's publications; the bio is a useful opener,
  never the substance.
* Publication counts are wildly uneven, from zero to a hundred. A roll-up that summed
  every matching paper would hand each query to whoever publishes most, so
  ``roll_up`` counts only a person's best few matches.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from insightnet.text import clean_text, extract_keywords

SCHEMA_VERSION = 1

DEFAULT_MODEL = os.getenv("INSIGHTNET_EMBED_MODEL", "gemini-embedding-001")
DEFAULT_DIMS = 256
DEFAULT_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
EMBED_BATCH = 100

#: Abstract prefix handed to the language model. Sanitized at build time so what is
#: committed is exactly what reaches the model, and shows up in a diff for review.
SNIPPET_LIMIT = 480
EMBED_TEXT_LIMIT = 8000
RESEARCHER_TITLES = 8
RESEARCHER_TOPICS = 15
WORK_AUTHORS = 6

BM25_K1 = 1.2
BM25_B = 0.75
RRF_K = 60
CANDIDATES = 300
FUSED_POOL = 60

#: Each researcher is credited for at most this many matching works. The cap, not the
#: decay, is what stops prolific authors winning every query on volume.
WORKS_PER_RESEARCHER = 3
TOP_RESEARCHERS = 10
EVIDENCE_PER_RESEARCHER = 2

#: Tools and centers are indexed and retrievable but **off by default**: this site is
#: about researchers and their publications, and insightnet.us already presents the
#: network's centers and what they build. Zero is a switch rather than a deletion — the
#: chunks stay in the index and `search(..., top_tools=3, top_orgs=3)` restores the old
#: behaviour without rebuilding anything.
TOP_TOOLS = 0
TOP_ORGS = 0

#: A matching tool says more about a center's current capability than a matching paper
#: does: publication lists are broad and historical, shipping software is specific.
#: Only consulted when centers are switched back on.
TOOL_WEIGHT = 2.0

#: There is deliberately **no score threshold** deciding whether a question is
#: answerable. Five candidate signals were measured against this corpus with twelve
#: on-topic and twelve off-topic questions, and none of them separates:
#:
#: =================  ==================  ==================  =========
#: signal             on-topic            off-topic           separates
#: =================  ==================  ==================  =========
#: top cosine         0.68 – 0.79         0.66 – 0.69         no
#: top − mean         0.112 – 0.156       0.083 – 0.143       no
#: z-score            3.27 – 4.44         3.45 – 5.07         no
#: score deviation    0.0315 – 0.0397     0.0236 – 0.0282     sentences only
#: top BM25           10.4 – 15.1         4.4 – 20.1          no
#: =================  ==================  ==================  =========
#:
#: Score deviation looked like the answer until bare keywords were tried: "dashboard"
#: gives 0.019 and "ERGM" 0.031 — below most off-topic questions — yet both retrieve
#: exactly the right record. Deviation partly measures how *specific the phrasing* is,
#: not how relevant the corpus is, so gating on it refuses the shortest, clearest
#: queries. "who won the world cup in 1998?" tops BM25 at 20.1 because a corpus of 7,738
#: documents contains "cup", "won" and "1998" somewhere.
#:
#: Relevance here is a semantic judgement, so it is left to the model, which sees both
#: the question and the retrieved records and answers ``NO_CONFIDENT_MATCH`` when they do
#: not support one. Retrieval refuses only when it structurally has nothing. Anyone
#: tempted to re-add a threshold should re-run the calibration first — the numbers above
#: are specific to gemini-embedding-001 at 256 dimensions.
RELEVANCE_IS_THE_MODELS_JOB = True

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
CONTROL_CHARACTERS = {ord(c): " " for c in map(chr, range(32)) if c not in "\t\n\r"}
PLURAL_EXCEPTIONS = frozenset({"ss", "us", "is", "as", "os"})

#: A query term this common carries no information about which chunk is relevant.
#: Deriving the cut from the corpus beats a hand-maintained stopword list: it adapts as
#: the corpus grows, and it drops domain filler ("disease", "health") that a general
#: English list would keep. Without it, "who can build dashboards?" ranks on "who".
#:
#: The absolute floor matters as much as the ratio: in a corpus of five documents a term
#: in one of them is already over any sensible ratio, so a ratio alone would discard
#: every term and match nothing.
MAX_DOCUMENT_FREQUENCY = 0.15
MIN_COMMON_DOCUMENTS = 8

#: Most bios end with a provenance note. It is identical across hundreds of profiles, so
#: embedding it adds no signal and spends prompt tokens on boilerplate. The site still
#: displays the note — it is only excluded from what gets indexed.
BIO_NOTE = re.compile(r"\s*note:\s*[^.]*ai-generated[^.]*\.?\s*$", re.IGNORECASE)

Embedder = Callable[[Sequence[str], str], list[list[float]]]


# ----------------------------------------------------------------------------------
# Text preparation
# ----------------------------------------------------------------------------------


def tokenize(value: str) -> list[str]:
    """Split text the same way the static site's keyword search does.

    Sharing the rule with ``keywordTerms`` in ``site/assets/app.js`` keeps the lexical
    half of retrieval consistent with the client-side fallback a visitor sees when the
    assistant is unavailable.
    """

    return TOKEN_PATTERN.findall(value.lower())


def _fold(token: str) -> str:
    """Fold a regular English plural onto its singular.

    Without this, "who can build dashboards?" misses every paper about a *dashboard*.
    Applied identically when indexing and when querying, so the two always agree; the
    endings excluded below are the ones where a trailing "s" is part of the word
    ("analysis", "virus", "bias").
    """

    if len(token) > 3 and token.endswith("s") and token[-2:] not in PLURAL_EXCEPTIONS:
        return token[:-1]
    return token


def lexical_terms(value: str) -> list[str]:
    """Tokens as the BM25 index stores them."""

    return [_fold(token) for token in tokenize(value)]


def sanitize(value: str, limit: int | None = None) -> str:
    """Normalize third-party text before it can reach a prompt.

    Abstracts are public text that anyone can influence by publishing a paper, so the
    angle brackets that delimit documents in the prompt are stripped here: a document
    must not be able to forge its own closing tag.
    """

    value = clean_text(value or "")
    value = value.translate(CONTROL_CHARACTERS)
    value = "".join(c for c in value if unicodedata.category(c) != "Cf")
    value = value.replace("<", " ").replace(">", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def _lines(*parts: str) -> str:
    return "\n".join(part for part in (p.strip() for p in parts) if part)


def strip_bio_note(bio: str) -> str:
    """Drop the trailing "this bio was AI-generated" note before indexing.

    Identical boilerplate on hundreds of profiles dilutes every researcher embedding
    equally and buys nothing back. Removing it here does not hide it from readers: the
    site renders ``profiles.json`` directly and is unaffected.
    """

    return BIO_NOTE.sub("", bio or "").strip()


def chunk_hash(text: str) -> str:
    """Stable key deciding whether a chunk needs re-embedding."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------------
# Chunk construction
# ----------------------------------------------------------------------------------


def _joined(values: Iterable[str]) -> list[str]:
    return [sanitize(value) for value in values if sanitize(value)]


def chunk_text(chunk: dict[str, Any]) -> str:
    """Compose the text that gets embedded and lexically indexed.

    Chunks store their structured pieces rather than a rendered blob. Composing here
    keeps the abstract on disk exactly once — storing both the rendered text and the
    snippet it contains nearly doubled the corpus — and leaves ``chunks.jsonl`` as a set
    of readable records rather than a wall of prose.
    """

    kind = chunk.get("kind")
    title = chunk.get("title") or ""
    keywords = "; ".join(chunk.get("keywords") or [])
    snippet = chunk.get("snippet") or ""

    if kind == "work":
        venue, year = chunk.get("venue") or "", chunk.get("year") or ""
        heading = f"{venue} ({year})" if venue and year else venue or str(year or "")
        authors = "; ".join(chunk.get("authors") or [])
        body = _lines(
            title,
            heading,
            f"Keywords: {keywords}" if keywords else "",
            snippet,
            f"Authors: {authors}" if authors else "",
        )
    elif kind == "researcher":
        heading = " — ".join(p for p in (chunk.get("role") or "", chunk.get("affiliation") or "") if p)
        expertise = "; ".join(chunk.get("expertise") or [])
        topics = "; ".join(chunk.get("topics") or [])
        recent = "; ".join(chunk.get("recent_titles") or [])
        body = _lines(
            title,
            heading,
            chunk.get("bio") or "",
            f"Expertise: {expertise}" if expertise else "",
            f"Topics: {topics}" if topics else "",
            f"Recent work: {recent}" if recent else "",
        )
    elif kind == "tool":
        status = " — ".join(p for p in (chunk.get("category") or "", chunk.get("status") or "") if p)
        body = _lines(
            title,
            status,
            chunk.get("affiliation") or "",
            snippet,
            f"Keywords: {keywords}" if keywords else "",
        )
    else:
        acronym = chunk.get("acronym") or ""
        focus = "; ".join(chunk.get("focus_areas") or [])
        body = _lines(
            f"{title} ({acronym})" if acronym else title,
            snippet,
            f"Focus areas: {focus}" if focus else "",
            f"Keywords: {keywords}" if keywords else "",
        )
    return body[:EMBED_TEXT_LIMIT]


def _finish(chunk: dict[str, Any]) -> dict[str, Any]:
    """Stamp the hash that decides whether this chunk needs re-embedding."""

    chunk["hash"] = chunk_hash(chunk_text(chunk))
    return chunk


def _work_chunk(work: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    return _finish(
        {
            "id": f"w:{work['id']}",
            "kind": "work",
            "title": sanitize(work.get("title") or "Untitled work"),
            "snippet": sanitize(detail.get("abstract") or "", SNIPPET_LIMIT),
            "keywords": _joined(work.get("keywords") or []),
            "authors": _joined(
                author.get("name") or "" for author in (detail.get("authors") or [])[:WORK_AUTHORS]
            ),
            "researcher_ids": list(work.get("researcher_ids") or []),
            "organization_ids": list(work.get("organization_ids") or []),
            "year": work.get("year") or 0,
            "venue": sanitize(work.get("venue") or ""),
            "url": work.get("url") or "",
            "doi": work.get("doi") or "",
            "work_id": work["id"],
        }
    )


def _researcher_chunk(
    researcher: dict[str, Any],
    organization: dict[str, Any],
    works: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Build a researcher record that is mostly derived from their publications.

    ``bio`` and ``expertise`` are carried when present but hold little topical signal:
    bios are short, generic institutional summaries and only about one researcher in
    seven lists any expertise. ``topics`` and ``recent_titles`` are what actually make a
    person findable for a specific method, pathogen, or tool.
    """

    topic_parts: list[str] = []
    for work in works:
        topic_parts.append(work.get("title") or "")
        topic_parts.extend(work.get("keywords") or [])

    return _finish(
        {
            "id": f"r:{researcher['id']}",
            "kind": "researcher",
            "title": sanitize(researcher.get("full_name") or researcher["id"]),
            "bio": sanitize(strip_bio_note(researcher.get("bio") or "")),
            "role": sanitize(researcher.get("role") or ""),
            "affiliation": sanitize(organization.get("name") or ""),
            "expertise": _joined(researcher.get("expertise") or []),
            "topics": extract_keywords(topic_parts, limit=RESEARCHER_TOPICS)
            if topic_parts
            else [],
            "recent_titles": _joined(
                work.get("title") or "" for work in works[:RESEARCHER_TITLES]
            ),
            "researcher_ids": [researcher["id"]],
            "organization_ids": [organization["id"]],
            "url": researcher.get("website") or researcher.get("orcid") or "",
            "work_count": len(works),
        }
    )


def _tool_chunk(tool: dict[str, Any], organization: dict[str, Any]) -> dict[str, Any]:
    return _finish(
        {
            "id": f"t:{tool['id']}",
            "kind": "tool",
            "title": sanitize(tool.get("name") or tool["id"]),
            "snippet": sanitize(tool.get("summary") or "", SNIPPET_LIMIT),
            "category": sanitize(tool.get("category") or ""),
            "status": sanitize(tool.get("status") or ""),
            "affiliation": sanitize(organization.get("name") or ""),
            "keywords": _joined(tool.get("keywords") or []),
            "researcher_ids": [],
            "organization_ids": [organization["id"]],
            "url": tool.get("url") or tool.get("repository") or "",
        }
    )


def _organization_chunk(organization: dict[str, Any]) -> dict[str, Any]:
    return _finish(
        {
            "id": f"o:{organization['id']}",
            "kind": "organization",
            "title": sanitize(organization.get("name") or organization["id"]),
            "acronym": sanitize(organization.get("acronym") or ""),
            "snippet": sanitize(organization.get("summary") or "", SNIPPET_LIMIT),
            "focus_areas": _joined(organization.get("focus_areas") or []),
            "keywords": _joined(organization.get("keywords") or []),
            "researcher_ids": [],
            "organization_ids": [organization["id"]],
            "url": organization.get("website") or "",
        }
    )


def _works_by_researcher(works: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for work in works:
        for researcher_id in work.get("researcher_ids") or []:
            grouped[researcher_id].append(work)
    for records in grouped.values():
        records.sort(key=lambda work: (work.get("published_at") or "", work.get("id") or ""), reverse=True)
    return grouped


def build_chunks(
    profiles: dict[str, Any],
    works_index: dict[str, Any],
    works_details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Turn the published snapshots into the flat chunk list, sorted by id."""

    details = (works_details or {}).get("details") or {}
    works = list(works_index.get("works") or [])
    grouped = _works_by_researcher(works)

    chunks = [_work_chunk(work, details.get(work["id"], {})) for work in works]
    for organization in profiles.get("organizations") or []:
        chunks.append(_organization_chunk(organization))
        for tool in organization.get("tools") or []:
            chunks.append(_tool_chunk(tool, organization))
        for researcher in organization.get("researchers") or []:
            chunks.append(
                _researcher_chunk(researcher, organization, grouped.get(researcher["id"], []))
            )
    chunks.sort(key=lambda chunk: chunk["id"])
    return chunks


# ----------------------------------------------------------------------------------
# Vectors
# ----------------------------------------------------------------------------------


def normalize(vector: Sequence[float]) -> list[float]:
    """Scale to unit length so cosine similarity is a plain dot product.

    Gemini does not L2-normalize embeddings requested below its full dimensionality,
    so this is required rather than defensive. Normalizing an already-normalized
    vector is harmless, so it is applied unconditionally.
    """

    norm = math.sqrt(sum(component * component for component in vector))
    if not norm:
        return [0.0] * len(vector)
    return [component / norm for component in vector]


def quantize(vector: Sequence[float]) -> str:
    """Store a unit vector as base64 int8 — a quarter the size, under 1% cosine error."""

    payload = bytes(
        (max(-127, min(127, round(component * 127))) & 0xFF) for component in normalize(vector)
    )
    return base64.b64encode(payload).decode("ascii")


def dequantize(encoded: str) -> list[float]:
    payload = base64.b64decode(encoded)
    return [int.from_bytes(bytes([byte]), "big", signed=True) / 127.0 for byte in payload]


# ----------------------------------------------------------------------------------
# Building
# ----------------------------------------------------------------------------------


@dataclass
class BuildResult:
    chunks: list[dict[str, Any]]
    vectors: dict[str, str]
    embedded: int = 0
    reused: int = 0
    dropped: int = 0
    dims: int = DEFAULT_DIMS
    model: str = DEFAULT_MODEL


def build_index(
    chunks: Sequence[dict[str, Any]],
    previous: BuildResult | None = None,
    embedder: Embedder | None = None,
    dims: int = DEFAULT_DIMS,
    model: str = DEFAULT_MODEL,
    batch: int = EMBED_BATCH,
) -> BuildResult:
    """Embed only what changed, copying every unchanged vector verbatim.

    Hash reuse is what keeps the weekly rebuild close to free and the committed diff
    close to empty; a full rebuild is thousands of calls, a typical week is dozens.
    """

    known: dict[str, str] = {}
    if previous is not None:
        previous_hashes = {chunk["id"]: chunk["hash"] for chunk in previous.chunks}
        known = {
            chunk_id: encoded
            for chunk_id, encoded in previous.vectors.items()
            if chunk_id in previous_hashes
        }
        previous_by_id = previous_hashes
    else:
        previous_by_id = {}

    vectors: dict[str, str] = {}
    pending: list[dict[str, Any]] = []
    reused = 0
    for chunk in chunks:
        encoded = known.get(chunk["id"])
        if encoded and previous_by_id.get(chunk["id"]) == chunk["hash"]:
            vectors[chunk["id"]] = encoded
            reused += 1
        else:
            pending.append(chunk)

    if pending:
        if embedder is None:
            raise ValueError(f"{len(pending)} chunk(s) need embedding but no embedder was supplied")
        for start in range(0, len(pending), batch):
            window = pending[start : start + batch]
            embeddings = embedder([chunk_text(chunk) for chunk in window], "RETRIEVAL_DOCUMENT")
            if len(embeddings) != len(window):
                raise ValueError(
                    f"embedder returned {len(embeddings)} vectors for {len(window)} chunks"
                )
            for chunk, embedding in zip(window, embeddings, strict=True):
                if len(embedding) != dims:
                    raise ValueError(
                        f"embedder returned {len(embedding)} dimensions, expected {dims}"
                    )
                vectors[chunk["id"]] = quantize(embedding)

    return BuildResult(
        chunks=list(chunks),
        vectors=vectors,
        embedded=len(pending),
        reused=reused,
        dropped=max(0, len(previous_by_id) - reused) if previous is not None else 0,
        dims=dims,
        model=model,
    )


# ----------------------------------------------------------------------------------
# On-disk format
# ----------------------------------------------------------------------------------

CHUNKS_NAME = "chunks.jsonl"
VECTORS_NAME = "vectors.jsonl"
MANIFEST_NAME = "manifest.json"


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _write_atomic(text: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary_name, output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def write_index(result: BuildResult, directory: str | Path, sources: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the three index files, sorted by id so git sees a minimal diff."""

    directory = Path(directory)
    chunk_lines = "".join(_dumps(chunk) + "\n" for chunk in result.chunks)
    vector_lines = "".join(
        _dumps({"id": chunk["id"], "v": result.vectors[chunk["id"]]}) + "\n"
        for chunk in result.chunks
        if chunk["id"] in result.vectors
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": result.model,
        "dims": result.dims,
        "quant": "int8-l2",
        "scale": 127,
        "chunks": len(result.chunks),
        "vectors": len(result.vectors),
        "kinds": dict(sorted(Counter(chunk["kind"] for chunk in result.chunks).items())),
        "sources": sources or {},
    }
    _write_atomic(chunk_lines, directory / CHUNKS_NAME)
    _write_atomic(vector_lines, directory / VECTORS_NAME)
    _write_atomic(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", directory / MANIFEST_NAME)
    return manifest


def read_index(directory: str | Path) -> BuildResult | None:
    """Read a previously written index, treating anything unreadable as absent."""

    directory = Path(directory)
    chunks_path = directory / CHUNKS_NAME
    vectors_path = directory / VECTORS_NAME
    if not chunks_path.exists():
        return None
    try:
        chunks = [
            json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line
        ]
        vectors: dict[str, str] = {}
        if vectors_path.exists():
            for line in vectors_path.read_text(encoding="utf-8").splitlines():
                if line:
                    record = json.loads(line)
                    vectors[record["id"]] = record["v"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"Ignoring unreadable previous index at {directory}: {exc}")
        return None
    manifest = {}
    manifest_path = directory / MANIFEST_NAME
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    return BuildResult(
        chunks=chunks,
        vectors=vectors,
        dims=manifest.get("dims", DEFAULT_DIMS),
        model=manifest.get("model", DEFAULT_MODEL),
    )


# ----------------------------------------------------------------------------------
# Retrieval
# ----------------------------------------------------------------------------------


@dataclass
class Index:
    """A loaded index with the lexical statistics needed for BM25.

    The statistics are derived at load time rather than committed, which keeps
    ``chunks.jsonl`` a clean, readable corpus — the artifact worth handing to another
    tool — instead of a serialized data structure.
    """

    chunks: list[dict[str, Any]]
    vectors: dict[str, str]
    dims: int = DEFAULT_DIMS
    manifest: dict[str, Any] = field(default_factory=dict)
    _frequencies: list[dict[str, int]] = field(default_factory=list, repr=False)
    _lengths: list[int] = field(default_factory=list, repr=False)
    _document_frequency: dict[str, int] = field(default_factory=dict, repr=False)
    _average_length: float = 0.0
    _matrix: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.by_id = {chunk["id"]: position for position, chunk in enumerate(self.chunks)}
        for chunk in self.chunks:
            counts = Counter(lexical_terms(chunk_text(chunk)))
            self._frequencies.append(counts)
            self._lengths.append(sum(counts.values()))
            for term in counts:
                self._document_frequency[term] = self._document_frequency.get(term, 0) + 1
        self._average_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    @classmethod
    def load(cls, directory: str | Path) -> Index:
        result = read_index(directory)
        if result is None:
            raise FileNotFoundError(f"no retrieval index in {directory}")
        manifest_path = Path(directory) / MANIFEST_NAME
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        )
        if manifest.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ValueError(
                f"index schema {manifest.get('schema_version')} does not match {SCHEMA_VERSION}"
            )
        return cls(
            chunks=result.chunks,
            vectors=result.vectors,
            dims=result.dims,
            manifest=manifest,
        )

    def matrix(self) -> Any:
        """Vectors as a numpy int8 matrix, or ``None`` when numpy is unavailable."""

        if self._matrix is None:
            try:
                import numpy
            except ImportError:
                return None
            rows = [
                base64.b64decode(self.vectors.get(chunk["id"], "")) or bytes(self.dims)
                for chunk in self.chunks
            ]
            self._matrix = numpy.frombuffer(b"".join(rows), dtype=numpy.int8).reshape(
                len(rows), self.dims
            )
        return self._matrix


def bm25(index: Index, terms: Sequence[str], limit: int = CANDIDATES) -> list[tuple[int, float]]:
    """Rank chunks lexically.

    This half of retrieval is what makes rare acronyms — ERGM, SEIR, MRSA — match
    exactly. Dense embeddings routinely blur them into a general topic.
    """

    total = len(index.chunks)
    if not total or not terms:
        return []
    scores: dict[int, float] = defaultdict(float)
    for term in set(terms):
        frequency = index._document_frequency.get(term, 0)
        if not frequency or frequency > max(
            MIN_COMMON_DOCUMENTS, total * MAX_DOCUMENT_FREQUENCY
        ):
            continue
        weight = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
        for position, counts in enumerate(index._frequencies):
            occurrences = counts.get(term, 0)
            if not occurrences:
                continue
            length = index._lengths[position] or 1
            denominator = occurrences + BM25_K1 * (
                1 - BM25_B + BM25_B * length / (index._average_length or 1)
            )
            scores[position] += weight * occurrences * (BM25_K1 + 1) / denominator
    ranked = sorted(scores.items(), key=lambda item: (-item[1], index.chunks[item[0]]["id"]))
    return ranked[:limit]


@dataclass
class DenseRanking:
    """Ranked chunks plus the shape of the whole score distribution.

    The distribution is what carries confidence. Absolute cosine does not: measured
    against this corpus, "best pizza in Chicago" scores 0.58 against an epidemiology
    paper and a genuine question scores 0.68, so no fixed cut separates them. What does
    separate them is whether the best match *stands out* — a real question produces an
    outlier, an irrelevant one produces a flat distribution.
    """

    ranked: list[tuple[int, float]] = field(default_factory=list)
    top: float = 0.0
    mean: float = 0.0
    deviation: float = 0.0

    @property
    def contrast(self) -> float:
        """Standard deviations between the best match and the corpus baseline."""

        return (self.top - self.mean) / self.deviation if self.deviation else 0.0


def dense(index: Index, query_vector: Sequence[float], limit: int = CANDIDATES) -> DenseRanking:
    """Rank chunks by cosine similarity against the query embedding."""

    if not index.chunks:
        return DenseRanking()
    query = normalize(query_vector)
    matrix = index.matrix()
    if matrix is not None:
        import numpy

        scores = (matrix.astype(numpy.float32) @ numpy.asarray(query, dtype=numpy.float32)) / 127.0
        order = numpy.argsort(-scores)[:limit]
        return DenseRanking(
            ranked=[(int(position), float(scores[position])) for position in order],
            top=float(scores.max()),
            mean=float(scores.mean()),
            deviation=float(scores.std()),
        )

    scored: list[tuple[int, float]] = []
    for position, chunk in enumerate(index.chunks):
        encoded = index.vectors.get(chunk["id"])
        if not encoded:
            continue
        vector = dequantize(encoded)
        scored.append((position, sum(a * b for a, b in zip(vector, query, strict=False))))
    if not scored:
        return DenseRanking()
    values = [value for _position, value in scored]
    mean = sum(values) / len(values)
    deviation = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    scored.sort(key=lambda item: (-item[1], index.chunks[item[0]]["id"]))
    return DenseRanking(
        ranked=scored[:limit], top=max(values), mean=mean, deviation=deviation
    )


def fuse(*rankings: Sequence[tuple[int, float]]) -> list[tuple[int, float]]:
    """Reciprocal rank fusion.

    BM25 scores and cosine similarities live on incomparable scales, and this corpus is
    far too small to tune a weighted blend against. Rank position is the only signal
    both lists agree on.
    """

    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (position, _score) in enumerate(ranking):
            scores[position] += 1.0 / (RRF_K + rank + 1)
    return sorted(scores.items(), key=lambda item: -item[1])


@dataclass
class Retrieval:
    researchers: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    organizations: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    confident: bool = False
    reason: str = ""
    #: Shape of the dense score distribution. Not a gate — see the note beside
    #: ``RELEVANCE_IS_THE_MODELS_JOB`` — but worth logging so a future threshold can be
    #: calibrated on real traffic rather than on invented questions.
    spread: float = 0.0


def roll_up(index: Index, fused: Sequence[tuple[int, float]]) -> list[dict[str, Any]]:
    """Turn ranked chunks into ranked people.

    A researcher's own chunk counts directly; their publications contribute only their
    best ``WORKS_PER_RESEARCHER`` matches, decayed by rank. Works with several listed
    researchers credit each of them fully — co-authorship is genuine evidence.
    """

    direct: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for position, score in fused[:FUSED_POOL]:
        chunk = index.chunks[position]
        if chunk["kind"] == "researcher":
            direct[chunk["researcher_ids"][0]] += score
        elif chunk["kind"] == "work":
            for researcher_id in chunk["researcher_ids"]:
                evidence[researcher_id].append((score, position))

    ranked: list[dict[str, Any]] = []
    for researcher_id in set(direct) | set(evidence):
        best = sorted(evidence.get(researcher_id, []), reverse=True)[:WORKS_PER_RESEARCHER]
        score = direct.get(researcher_id, 0.0) + sum(
            value / math.sqrt(rank + 1) for rank, (value, _position) in enumerate(best)
        )
        ranked.append(
            {
                "id": researcher_id,
                "score": round(score, 6),
                "evidence": [index.chunks[position]["id"] for _value, position in best],
            }
        )
    ranked.sort(key=lambda entry: (-entry["score"], entry["id"]))
    return ranked


def roll_up_organizations(index: Index, fused: Sequence[tuple[int, float]]) -> list[dict[str, Any]]:
    """Turn ranked chunks into ranked centers.

    A center is the answer when no individual is. Tools have no owning researcher, but
    they do have an owning center, so "who can build dashboards?" resolves to the center
    that builds the dashboard rather than to whichever author happens to share wording
    with the question.

    Tools count for more than papers here: a center's publication list is broad, while
    shipping a tool is a specific, current capability. The same best-N cap as ``roll_up``
    applies, so a center with ninety researchers cannot win on breadth alone.
    """

    direct: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for position, score in fused[:FUSED_POOL]:
        chunk = index.chunks[position]
        if chunk["kind"] == "organization":
            direct[chunk["organization_ids"][0]] += score
        elif chunk["kind"] in ("tool", "work"):
            weight = TOOL_WEIGHT if chunk["kind"] == "tool" else 1.0
            for organization_id in chunk.get("organization_ids") or []:
                evidence[organization_id].append((score * weight, position))

    ranked: list[dict[str, Any]] = []
    for organization_id in set(direct) | set(evidence):
        best = sorted(evidence.get(organization_id, []), reverse=True)[:WORKS_PER_RESEARCHER]
        score = direct.get(organization_id, 0.0) + sum(
            value / math.sqrt(rank + 1) for rank, (value, _position) in enumerate(best)
        )
        profile = index.chunks[index.by_id[f"o:{organization_id}"]] if f"o:{organization_id}" in index.by_id else {}
        ranked.append(
            {
                "id": organization_id,
                "name": profile.get("title", organization_id),
                "acronym": profile.get("acronym", ""),
                "url": profile.get("url", ""),
                "score": round(score, 6),
                "evidence": [index.chunks[position]["id"] for _value, position in best],
            }
        )
    ranked.sort(key=lambda entry: (-entry["score"], entry["id"]))
    return ranked


def search(
    index: Index,
    question: str,
    query_vector: Sequence[float] | None = None,
    *,
    top_researchers: int = TOP_RESEARCHERS,
    top_tools: int = TOP_TOOLS,
    top_orgs: int = TOP_ORGS,
) -> Retrieval:
    """Run the hybrid retrieval and roll-up.

    ``query_vector`` may be omitted to run lexically only, which is what happens when
    embeddings are unavailable — degraded, but still useful, and it keeps the CLI usable
    before any cloud credentials exist.

    The three caps are arguments rather than constants read at call time so that turning
    tools and centers back on is a keyword argument, not an edit: they default to zero
    (see ``TOP_TOOLS``), and passing a positive value restores that half of the answer
    from the index as it already stands.

    Retrieval returns its best candidates and reports how confident the *distribution*
    looked; it does not decide whether the question is answerable. See the note beside
    ``RELEVANCE_IS_THE_MODELS_JOB`` for the measurements behind that decision.
    """

    lexical = bm25(index, lexical_terms(question))
    semantic = dense(index, query_vector) if query_vector else DenseRanking()
    fused = fuse(lexical, semantic.ranked) if semantic.ranked else fuse(lexical)
    if not fused:
        return Retrieval(reason="no_match")

    people = roll_up(index, fused)[:top_researchers]

    citation_ids: list[str] = []
    researchers: list[dict[str, Any]] = []
    for person in people:
        position = index.by_id.get(f"r:{person['id']}")
        profile = index.chunks[position] if position is not None else {}
        chosen = person["evidence"][:EVIDENCE_PER_RESEARCHER]
        citation_ids.extend(chosen)
        researchers.append(
            {
                "id": person["id"],
                "name": profile.get("title", person["id"]),
                "role": profile.get("role", ""),
                "organization_ids": profile.get("organization_ids", []),
                "snippet": sanitize(chunk_text(profile), SNIPPET_LIMIT) if profile else "",
                "score": person["score"],
                "evidence": chosen,
            }
        )

    seen: set[str] = set()
    citations = []
    for chunk_id in citation_ids:
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk = index.chunks[index.by_id[chunk_id]]
        citations.append(
            {
                "id": chunk["id"],
                "work_id": chunk.get("work_id", ""),
                "title": chunk["title"],
                "year": chunk.get("year", 0),
                "venue": chunk.get("venue", ""),
                "url": chunk.get("url", ""),
                "doi": chunk.get("doi", ""),
                "snippet": chunk.get("snippet", ""),
                "researcher_ids": chunk.get("researcher_ids", []),
            }
        )

    # Tools have no owning researcher, but they do have an owning center, so a matched
    # tool is reported with the center that builds it and the center is ranked alongside
    # it. That is the honest answer to "who can build dashboards?" — a team, not a name.
    def _center_names(chunk: dict[str, Any]) -> list[str]:
        names = []
        for organization_id in chunk.get("organization_ids") or []:
            position = index.by_id.get(f"o:{organization_id}")
            names.append(index.chunks[position]["title"] if position is not None else organization_id)
        return names

    # Both roll-ups are skipped rather than computed and sliced away, so the default
    # configuration does no work for the half of the answer it does not want.
    tools = (
        [
            {
                "id": index.chunks[position]["id"],
                "title": index.chunks[position]["title"],
                "snippet": index.chunks[position].get("snippet", ""),
                "url": index.chunks[position].get("url", ""),
                "category": index.chunks[position].get("category", ""),
                "organization_ids": index.chunks[position].get("organization_ids", []),
                "organization_names": _center_names(index.chunks[position]),
                "score": round(score, 6),
            }
            for position, score in fused[:FUSED_POOL]
            if index.chunks[position]["kind"] == "tool"
        ][:top_tools]
        if top_tools > 0
        else []
    )

    organizations = roll_up_organizations(index, fused)[:top_orgs] if top_orgs > 0 else []

    # With tools and centers enabled, a tool-shaped question can rank the right software
    # and the right center without crediting a single person, and that is still a useful
    # answer — so refuse only when nothing at all came back. On the default settings this
    # reduces to "refuse unless a researcher matched", which is the intended behaviour:
    # a question this site cannot answer with a person belongs in the keyword search.
    if not researchers and not tools and not organizations:
        return Retrieval(reason="no_match")

    return Retrieval(
        researchers=researchers,
        tools=tools,
        organizations=organizations,
        citations=citations,
        confident=True,
        spread=round(semantic.deviation, 5),
    )


# ----------------------------------------------------------------------------------
# Embedding client
# ----------------------------------------------------------------------------------


def vertex_embedder(
    model: str = DEFAULT_MODEL,
    dims: int = DEFAULT_DIMS,
    project: str = "",
    location: str = DEFAULT_LOCATION,
) -> Embedder:
    """Embedder backed by Vertex AI.

    Authentication is Application Default Credentials, so there is no API key to store,
    leak, or rotate: in Cloud Run the service account is the credential, and in CI it
    comes from Workload Identity Federation.
    """

    from google import genai  # imported lazily so the builder is importable without it
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=project or os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        location=location,
    )

    def embed(texts: Sequence[str], task_type: str) -> list[list[float]]:
        response = client.models.embed_content(
            model=model,
            contents=list(texts),
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=dims),
        )
        return [list(item.values) for item in response.embeddings]

    return embed


def embed_query(embedder: Embedder, question: str) -> list[float]:
    """Embed a question with the query task type.

    Documents and questions must use different task types with this model family;
    using one for both is a silent, sizeable quality loss rather than an error.
    """

    return normalize(embedder([question], "RETRIEVAL_QUERY")[0])


__all__ = [
    "SCHEMA_VERSION",
    "BuildResult",
    "DenseRanking",
    "Index",
    "Retrieval",
    "build_chunks",
    "build_index",
    "chunk_hash",
    "chunk_text",
    "dense",
    "dequantize",
    "embed_query",
    "fuse",
    "lexical_terms",
    "normalize",
    "quantize",
    "read_index",
    "roll_up",
    "roll_up_organizations",
    "sanitize",
    "search",
    "strip_bio_note",
    "tokenize",
    "vertex_embedder",
    "write_index",
]
