"""Collect scholarly works (journal articles and preprints) for network researchers.

Every request targets a public, documented API: the ORCID public record, Europe PMC,
NCBI E-utilities, the arXiv Atom API, and the bioRxiv/medRxiv details API. No API key
is required, though ``NCBI_API_KEY`` raises the PubMed rate limit when it is present.

Attribution is identifier-first. A researcher's ORCID drives collection; a researcher is
only searched by name when their profile opts in with an explicit ``pubmed_query`` or
``arxiv_query``, so people who share a name never silently collect each other's papers.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.etree import ElementTree

import feedparser
import requests

from insightnet.collectors import SourceClient
from insightnet.text import clean_text

SCHEMA_VERSION = 2

ORCID_API = "https://pub.orcid.org/v3.0"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUTILS_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ARXIV_API = "http://export.arxiv.org/api/query"
BIORXIV_API = "https://api.biorxiv.org/details"
CROSSREF_API = "https://api.crossref.org/works"

# Europe PMC accepts long boolean queries; smaller batches keep each request cheap to
# retry when a single identifier is malformed.
ENRICHMENT_BATCH = 20
MAX_AUTHORS = 200
PREPRINT_DOI_PREFIX = "10.1101/"
ARXIV_DOI_PREFIX = "10.48550/arxiv."

# Crossref is queried one DOI at a time, so bound how much of a single run it can take.
MAX_CROSSREF_LOOKUPS = 3000
# Crossref routes polite-pool traffic by contact address; override for a real deployment.
CROSSREF_CONTACT = os.getenv("INSIGHTNET_CONTACT_EMAIL", "insightnet-bot@users.noreply.github.com")


@dataclass
class WorksResult:
    """Outcome of one researcher/source pair, mirroring activity collection health."""

    status: str = "ok"
    message: str = ""
    works: list[dict[str, Any]] = field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_doi(value: str) -> str:
    value = clean_text(str(value or "")).lower()
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value).strip()
    return value if value.startswith("10.") else ""


def _normalize_pmid(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if 1 <= len(digits) <= 9 else ""


def _normalize_arxiv_id(value: str) -> str:
    value = clean_text(str(value or "")).strip()
    value = re.sub(r"^(https?://arxiv\.org/(abs|pdf)/|arxiv:\s*)", "", value, flags=re.IGNORECASE)
    if value.lower().startswith(ARXIV_DOI_PREFIX):
        value = value[len(ARXIV_DOI_PREFIX) :]
    value = re.sub(r"v\d+$", "", value)
    modern = re.fullmatch(r"\d{4}\.\d{4,5}", value)
    legacy = re.fullmatch(r"[a-z-]+(\.[A-Za-z]{2})?/\d{7}", value)
    return value if modern or legacy else ""


def _date_parts(year: Any, month: Any = "", day: Any = "") -> str:
    """Build an ISO date, padding unknown month/day so records stay sortable."""

    year_text = re.sub(r"\D", "", str(year or ""))
    if len(year_text) != 4:
        return ""
    month_text = re.sub(r"\D", "", str(month or "")) or "1"
    day_text = re.sub(r"\D", "", str(day or "")) or "1"
    try:
        parsed = datetime(int(year_text), min(max(int(month_text), 1), 12), 1, tzinfo=UTC)
        day_number = min(max(int(day_text), 1), 28 if parsed.month == 2 else 30)
    except (TypeError, ValueError):
        return ""
    return f"{parsed.year:04d}-{parsed.month:02d}-{day_number:02d}"


def _iso_date(value: str) -> str:
    match = re.match(r"(\d{4})[-/]?(\d{2})?[-/]?(\d{2})?", clean_text(str(value or "")))
    return _date_parts(*match.groups()) if match else ""


MONTHS = {
    name.lower(): index
    for index, name in enumerate(
        [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
        start=1,
    )
}


# Preprint servers appear in the journal-title field of several APIs. Keeping them out of
# ``venue`` is what lets a preprint be told apart from the journal that later published it.
PREPRINT_VENUES = {
    "medrxiv": "medRxiv",
    "biorxiv": "bioRxiv",
    "arxiv": "arXiv",
    "research square": "Research Square",
    "ssrn": "SSRN",
    "preprints.org": "Preprints.org",
    "authorea": "Authorea",
    "osf preprints": "OSF Preprints",
}


def _split_venue(title: Any) -> tuple[str, str]:
    """Split a publication venue into ``(journal, preprint_server)``."""

    cleaned = clean_text(str(title or ""))
    lowered = cleaned.lower()
    for needle, label in PREPRINT_VENUES.items():
        if needle in lowered:
            return "", label
    return cleaned, ""


def _month_number(value: str) -> str:
    value = clean_text(str(value or "")).lower()
    if value[:3] in MONTHS:
        return str(MONTHS[value[:3]])
    return value


def _work_record(**values: Any) -> dict[str, Any]:
    """Normalize one work into the shape stored in ``works.json``."""

    doi = _normalize_doi(values.get("doi", ""))
    pmid = _normalize_pmid(values.get("pmid", ""))
    arxiv = _normalize_arxiv_id(values.get("arxiv_id", ""))
    if not arxiv and doi.startswith(ARXIV_DOI_PREFIX):
        arxiv = _normalize_arxiv_id(doi)
    authors = []
    for author in values.get("authors", []) or []:
        if isinstance(author, str):
            author = {"name": author}
        name = clean_text(str(author.get("name", "")), 120)
        if name:
            authors.append({"name": name, "orcid": str(author.get("orcid", "") or "")})
    keywords = [clean_text(str(word), 80).lower() for word in values.get("keywords", []) or []]
    keywords = [word for word in dict.fromkeys(keywords) if word][:15]

    work_type = values.get("type", "article")
    preprint_server = values.get("preprint_server", "")
    if arxiv and doi.startswith(ARXIV_DOI_PREFIX):
        work_type = "preprint"
        preprint_server = preprint_server or "arXiv"

    url = clean_text(str(values.get("url", "")))
    if not url and doi:
        url = f"https://doi.org/{doi}"
    if not url and pmid:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if not url and arxiv:
        url = f"https://arxiv.org/abs/{arxiv}"

    published_at = values.get("published_at", "")
    return {
        "title": clean_text(str(values.get("title", "")), 400),
        "abstract": clean_text(
            str(values.get("abstract", "")), int(values.get("abstract_limit", 1500))
        ),
        "keywords": keywords,
        "published_at": published_at,
        "year": int(published_at[:4]) if published_at[:4].isdigit() else 0,
        "url": url,
        "doi": doi,
        "pmid": pmid,
        "pmcid": clean_text(str(values.get("pmcid", "")), 40),
        "arxiv_id": arxiv,
        "venue": clean_text(str(values.get("venue", "")), 200),
        "type": work_type,
        "preprint_server": preprint_server,
        "authors": authors[:MAX_AUTHORS],
        "author_count": len(authors),
        "sources": [values["source"]] if values.get("source") else [],
        "researcher_ids": [],
        "organization_ids": [],
    }


def work_keys(record: dict[str, Any]) -> list[str]:
    """Every identifier a work can be recognized by, most authoritative first."""

    keys = []
    if record.get("doi"):
        keys.append(f"doi:{record['doi']}")
    if record.get("pmid"):
        keys.append(f"pmid:{record['pmid']}")
    if record.get("arxiv_id"):
        keys.append(f"arxiv:{record['arxiv_id'].lower()}")
    title = re.sub(r"[^a-z0-9]+", "", str(record.get("title", "")).lower())
    if title:
        keys.append(f"title:{title[:120]}")
    return keys


def _work_id(record: dict[str, Any]) -> str:
    keys = work_keys(record)
    seed = keys[0] if keys else repr(sorted(record.items()))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _merge_into(target: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Fill gaps in ``target`` from ``extra`` without discarding richer values."""

    for key in ("title", "abstract", "url", "doi", "pmid", "pmcid", "arxiv_id", "venue"):
        if not target.get(key) and extra.get(key):
            target[key] = extra[key]

    # A year-only date arrives padded to January 1st. Prefer any date that carries a real
    # month and day, so ORCID's coarse years do not mask a precise publication date.
    incoming = extra.get("published_at", "")
    current = target.get("published_at", "")
    if incoming and (
        not current or (current.endswith("-01-01") and not incoming.endswith("-01-01"))
    ):
        target["published_at"] = incoming
        target["year"] = extra.get("year", 0) or target.get("year", 0)

    if len(extra.get("authors", [])) > len(target.get("authors", [])):
        target["authors"] = extra["authors"]
        target["author_count"] = extra.get("author_count", len(extra["authors"]))
    merged_keywords = list(target.get("keywords", [])) + list(extra.get("keywords", []))
    target["keywords"] = list(dict.fromkeys(merged_keywords))[:15]
    if extra.get("preprint_server") and not target.get("preprint_server"):
        target["preprint_server"] = extra["preprint_server"]
    if not target.get("type") and extra.get("type"):
        target["type"] = extra["type"]
    target["sources"] = list(dict.fromkeys(target.get("sources", []) + extra.get("sources", [])))
    return target


def _finalize_type(work: dict[str, Any]) -> dict[str, Any]:
    """Classify a merged record once every identifier is known.

    A preprint that was later published keeps its ``preprint_server`` for provenance but
    is reported as an article, because the journal DOI or PubMed ID is the version of
    record.
    """

    if work.get("venue"):
        work["type"] = "article"
    elif work.get("preprint_server"):
        work["type"] = "preprint"
    else:
        # No venue was reported either way, so fall back to the identifiers: a DOI that
        # is not an arXiv or bioRxiv/medRxiv DOI implies a published article.
        published = bool(work.get("pmid")) or (
            bool(work.get("doi"))
            and not work["doi"].startswith(ARXIV_DOI_PREFIX)
            and not work["doi"].startswith(PREPRINT_DOI_PREFIX)
        )
        work["type"] = "article" if published else work.get("type") or "article"
    return work


def is_citable(work: dict[str, Any]) -> bool:
    """Whether a record can be linked or verified by a reader.

    ORCID lists outputs such as software repositories with no identifier and no URL.
    They cannot be opened, cited, or deduplicated reliably, so they are left out.
    """

    return bool(work.get("doi") or work.get("pmid") or work.get("arxiv_id") or work.get("url"))


# --------------------------------------------------------------------------------------
# Europe PMC
# --------------------------------------------------------------------------------------


def _europepmc_preprint_server(payload: dict[str, Any], doi: str, arxiv: str) -> str:
    candidates = [
        str(payload.get("bookOrReportDetails", {}).get("publisher", "")),
        str(payload.get("journalInfo", {}).get("journal", {}).get("title", "")),
        str(payload.get("publisher", "")),
    ]
    for candidate in candidates:
        lowered = candidate.lower()
        for server in ("medrxiv", "biorxiv", "arxiv", "research square", "ssrn"):
            if server in lowered:
                return {"medrxiv": "medRxiv", "biorxiv": "bioRxiv", "arxiv": "arXiv"}.get(
                    server, candidate.strip()
                )
    if arxiv:
        return "arXiv"
    if doi.startswith(PREPRINT_DOI_PREFIX):
        return "medRxiv/bioRxiv"
    return ""


def _from_europepmc(payload: dict[str, Any], abstract_limit: int) -> dict[str, Any]:
    journal = payload.get("journalInfo", {}) or {}
    doi = _normalize_doi(payload.get("doi", ""))
    arxiv = ""
    if doi.startswith(ARXIV_DOI_PREFIX):
        arxiv = _normalize_arxiv_id(doi)

    keywords = [str(word) for word in (payload.get("keywordList", {}) or {}).get("keyword", [])]
    for heading in (payload.get("meshHeadingList", {}) or {}).get("meshHeading", []):
        if heading.get("descriptorName"):
            keywords.append(str(heading["descriptorName"]))

    authors = []
    for author in (payload.get("authorList", {}) or {}).get("author", []):
        name = author.get("fullName") or author.get("collectiveName") or ""
        identifier = author.get("authorId", {}) or {}
        authors.append(
            {
                "name": name,
                "orcid": identifier.get("value", "") if identifier.get("type") == "ORCID" else "",
            }
        )
    if not authors and payload.get("authorString"):
        authors = [{"name": name.strip()} for name in str(payload["authorString"]).split(",")]

    is_preprint = (
        str(payload.get("source", "")).upper() == "PPR"
        or "preprint" in str((payload.get("pubTypeList", {}) or {}).get("pubType", "")).lower()
    )
    venue, preprint_server = _split_venue((journal.get("journal", {}) or {}).get("title", ""))
    if is_preprint:
        venue = ""
        preprint_server = preprint_server or _europepmc_preprint_server(payload, doi, arxiv)

    published = (
        _iso_date(payload.get("firstPublicationDate", ""))
        or _iso_date(journal.get("printPublicationDate", ""))
        or _date_parts(payload.get("pubYear", "") or journal.get("yearOfPublication", ""))
    )
    return _work_record(
        title=payload.get("title", ""),
        abstract=payload.get("abstractText", ""),
        abstract_limit=abstract_limit,
        keywords=keywords,
        published_at=published,
        doi=doi,
        pmid=payload.get("pmid", ""),
        pmcid=payload.get("pmcid", ""),
        arxiv_id=arxiv,
        venue=venue,
        type="preprint" if is_preprint else "article",
        preprint_server=preprint_server,
        authors=authors,
        source="europepmc",
    )


def _europepmc_search(
    client: SourceClient, query: str, limit: int, abstract_limit: int
) -> list[dict[str, Any]]:
    works: list[dict[str, Any]] = []
    cursor = "*"
    while len(works) < limit:
        response = client.get(
            EUROPEPMC_API,
            respect_robots=False,
            params={
                "query": query,
                "resultType": "core",
                "format": "json",
                "pageSize": min(100, limit - len(works)),
                "cursorMark": cursor,
            },
        )
        payload = response.json()
        results = (payload.get("resultList", {}) or {}).get("result", [])
        works.extend(_from_europepmc(row, abstract_limit) for row in results)
        next_cursor = payload.get("nextCursorMark", "")
        if not results or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return works[:limit]


def collect_europepmc_by_orcid(
    client: SourceClient, researcher: dict[str, Any], limits: dict[str, int]
) -> WorksResult:
    identifier = researcher.get("orcid_id", "")
    if not identifier:
        return WorksResult(status="skipped", message="No ORCID on this profile")
    works = _europepmc_search(
        client,
        f'AUTHORID:"{identifier}"',
        limits["max_works"],
        limits["abstract_limit"],
    )
    return WorksResult(works=works, message=f"Read {len(works)} Europe PMC record(s) by ORCID")


# --------------------------------------------------------------------------------------
# ORCID public record
# --------------------------------------------------------------------------------------


def collect_orcid_works(
    client: SourceClient, researcher: dict[str, Any], limits: dict[str, int]
) -> WorksResult:
    identifier = researcher.get("orcid_id", "")
    if not identifier:
        return WorksResult(status="skipped", message="No ORCID on this profile")
    response = client.get(
        f"{ORCID_API}/{identifier}/works",
        respect_robots=False,
        headers={"Accept": "application/json"},
    )
    works = []
    for group in response.json().get("group", []):
        summaries = group.get("work-summary", []) or []
        if not summaries:
            continue
        summary = summaries[0]
        identifiers = {"doi": "", "pmid": "", "arxiv": ""}
        for external in (summary.get("external-ids", {}) or {}).get("external-id", []):
            id_type = str(external.get("external-id-type", "")).lower()
            if id_type in identifiers and not identifiers[id_type]:
                identifiers[id_type] = str(external.get("external-id-value", ""))
        date = summary.get("publication-date") or {}
        published = _date_parts(
            (date.get("year") or {}).get("value", ""),
            (date.get("month") or {}).get("value", ""),
            (date.get("day") or {}).get("value", ""),
        )
        work_type = str(summary.get("type", "")).lower().replace("_", "-")
        venue, preprint_server = _split_venue((summary.get("journal-title") or {}).get("value", ""))
        works.append(
            _work_record(
                title=((summary.get("title") or {}).get("title") or {}).get("value", ""),
                published_at=published,
                url=((summary.get("url") or {}) or {}).get("value", ""),
                doi=identifiers["doi"],
                pmid=identifiers["pmid"],
                arxiv_id=identifiers["arxiv"],
                venue="" if work_type == "preprint" else venue,
                preprint_server=preprint_server,
                type="preprint" if work_type == "preprint" else "article",
                abstract_limit=limits["abstract_limit"],
                source="orcid",
            )
        )
    works = [work for work in works if work["title"] and is_citable(work)]
    works.sort(key=lambda work: work["published_at"], reverse=True)
    works = works[: limits["max_works"]]
    return WorksResult(works=works, message=f"Read {len(works)} work summary/summaries from ORCID")


# --------------------------------------------------------------------------------------
# PubMed (NCBI E-utilities)
# --------------------------------------------------------------------------------------


def _eutils_params() -> dict[str, str]:
    params = {"db": "pubmed", "tool": "insightnet-dashboard", "email": "insightnet-bot@example.org"}
    key = os.getenv("NCBI_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    return params


def _from_pubmed(article: ElementTree.Element, abstract_limit: int) -> dict[str, Any]:
    citation = article.find("MedlineCitation")
    if citation is None:
        return {}
    meta = citation.find("Article")
    if meta is None:
        return {}

    abstract = " ".join(
        f"{node.get('Label')}: {node.text or ''}" if node.get("Label") else (node.text or "")
        for node in meta.findall("./Abstract/AbstractText")
    )
    keywords = [node.text or "" for node in citation.findall("./KeywordList/Keyword")]
    keywords += [
        node.text or "" for node in citation.findall("./MeshHeadingList/MeshHeading/DescriptorName")
    ]

    authors = []
    for author in meta.findall("./AuthorList/Author"):
        last = (author.findtext("LastName") or "").strip()
        fore = (author.findtext("ForeName") or "").strip()
        name = (
            " ".join(part for part in (fore, last) if part)
            or (author.findtext("CollectiveName") or "").strip()
        )
        orcid = ""
        for identifier in author.findall("Identifier"):
            if identifier.get("Source") == "ORCID":
                orcid = re.sub(r".*?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", r"\1", identifier.text or "")
        if name:
            authors.append({"name": name, "orcid": orcid})

    doi = ""
    for location in meta.findall("./ELocationID"):
        if location.get("EIdType") == "doi":
            doi = location.text or ""
    for identifier in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if identifier.get("IdType") == "doi" and not doi:
            doi = identifier.text or ""

    published = _date_parts(
        meta.findtext("./ArticleDate/Year") or meta.findtext("./Journal/JournalIssue/PubDate/Year"),
        _month_number(
            meta.findtext("./ArticleDate/Month")
            or meta.findtext("./Journal/JournalIssue/PubDate/Month")
            or ""
        ),
        meta.findtext("./ArticleDate/Day") or meta.findtext("./Journal/JournalIssue/PubDate/Day"),
    )
    journal, journal_server = _split_venue(meta.findtext("./Journal/Title") or "")
    return _work_record(
        title="".join(meta.find("ArticleTitle").itertext())
        if meta.find("ArticleTitle") is not None
        else "",
        abstract=abstract,
        abstract_limit=abstract_limit,
        keywords=keywords,
        published_at=published,
        pmid=citation.findtext("PMID") or "",
        doi=doi,
        venue=journal,
        preprint_server=journal_server,
        type="preprint" if journal_server else "article",
        authors=authors,
        source="pubmed",
    )


def _pubmed_fetch(
    client: SourceClient, pubmed_ids: list[str], abstract_limit: int
) -> list[dict[str, Any]]:
    works = []
    for start in range(0, len(pubmed_ids), 100):
        batch = pubmed_ids[start : start + 100]
        response = client.get(
            f"{EUTILS_API}/efetch.fcgi",
            respect_robots=False,
            params={**_eutils_params(), "id": ",".join(batch), "retmode": "xml"},
        )
        root = ElementTree.fromstring(response.content)
        for article in root.findall("PubmedArticle"):
            record = _from_pubmed(article, abstract_limit)
            if record and record["title"]:
                works.append(record)
    return works


def collect_pubmed(
    client: SourceClient, researcher: dict[str, Any], limits: dict[str, int]
) -> WorksResult:
    query = researcher.get("pubmed_query", "").strip()
    identifier = researcher.get("orcid_id", "")
    if not query and identifier:
        query = f"{identifier}[auid]"
    if not query:
        return WorksResult(
            status="skipped",
            message="No ORCID and no pubmed_query; add pubmed_query to search PubMed by name",
        )
    response = client.get(
        f"{EUTILS_API}/esearch.fcgi",
        respect_robots=False,
        params={
            **_eutils_params(),
            "term": query,
            "retmax": limits["max_works"],
            "retmode": "json",
            "sort": "date",
        },
    )
    pubmed_ids = (response.json().get("esearchresult", {}) or {}).get("idlist", [])
    if not pubmed_ids:
        return WorksResult(message="PubMed returned no records for this query")
    works = _pubmed_fetch(client, pubmed_ids, limits["abstract_limit"])
    return WorksResult(works=works, message=f"Read {len(works)} PubMed record(s)")


# --------------------------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------------------------


def _from_arxiv(entry: Any, abstract_limit: int) -> dict[str, Any]:
    arxiv_id = _normalize_arxiv_id(str(entry.get("id", "")))
    doi = _normalize_doi(str(entry.get("arxiv_doi", "") or ""))
    categories = [tag.get("term", "") for tag in entry.get("tags", []) or []]
    return _work_record(
        title=entry.get("title", ""),
        abstract=entry.get("summary", ""),
        abstract_limit=abstract_limit,
        keywords=categories,
        published_at=_iso_date(str(entry.get("published", ""))[:10]),
        url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else entry.get("link", ""),
        doi=doi,
        arxiv_id=arxiv_id,
        venue="",
        type="preprint",
        preprint_server="arXiv",
        authors=[{"name": author.get("name", "")} for author in entry.get("authors", []) or []],
        source="arxiv",
    )


def _arxiv_query(
    client: SourceClient, params: dict[str, Any], limit: int, abstract_limit: int
) -> list[dict[str, Any]]:
    response = client.get(ARXIV_API, respect_robots=False, params=params)
    feed = feedparser.parse(response.content)
    works = [_from_arxiv(entry, abstract_limit) for entry in feed.entries[:limit]]
    return [work for work in works if work["title"]]


def collect_arxiv(
    client: SourceClient, researcher: dict[str, Any], limits: dict[str, int]
) -> WorksResult:
    query = researcher.get("arxiv_query", "").strip()
    if not query:
        return WorksResult(
            status="skipped",
            message="No arxiv_query configured; add one to search arXiv by author name",
        )
    works = _arxiv_query(
        client,
        {
            "search_query": query if ":" in query else f'au:"{query}"',
            "start": 0,
            "max_results": min(limits["max_works"], 100),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        limits["max_works"],
        limits["abstract_limit"],
    )
    return WorksResult(works=works, message=f"Read {len(works)} arXiv preprint(s)")


# --------------------------------------------------------------------------------------
# Enrichment: fill in abstracts, keywords, and coauthors for sparse records
# --------------------------------------------------------------------------------------


def _enrich_via_europepmc(
    client: SourceClient, sparse: list[dict[str, Any]], abstract_limit: int
) -> int:
    """Look sparse works up in Europe PMC by DOI or PubMed ID, in batches."""

    lookups: dict[str, dict[str, Any]] = {}
    for work in sparse:
        if work.get("doi"):
            lookups[f'DOI:"{work["doi"]}"'] = work
        elif work.get("pmid"):
            lookups[f'EXT_ID:"{work["pmid"]}" AND SRC:"MED"'] = work
    if not lookups:
        return 0

    clauses = list(lookups)
    enriched = 0
    for start in range(0, len(clauses), ENRICHMENT_BATCH):
        batch = clauses[start : start + ENRICHMENT_BATCH]
        try:
            results = _europepmc_search(
                client, " OR ".join(f"({clause})" for clause in batch), 100, abstract_limit
            )
        except (requests.RequestException, ValueError):
            continue
        by_key = {}
        for result in results:
            for key in work_keys(result):
                by_key.setdefault(key, result)
        for work in (lookups[clause] for clause in batch):
            match = next((by_key[key] for key in work_keys(work) if key in by_key), None)
            if match:
                _merge_into(work, match)
                enriched += 1
    return enriched


def _enrich_via_arxiv(client: SourceClient, sparse: list[dict[str, Any]], limit: int) -> int:
    targets = [work for work in sparse if work.get("arxiv_id")][:50]
    if not targets:
        return 0
    by_id = {work["arxiv_id"]: work for work in targets}
    try:
        results = _arxiv_query(
            client,
            {"id_list": ",".join(by_id), "max_results": len(by_id)},
            len(by_id),
            limit,
        )
    except (requests.RequestException, ValueError):
        return 0
    enriched = 0
    for result in results:
        target = by_id.get(result.get("arxiv_id", ""))
        if target:
            _merge_into(target, result)
            enriched += 1
    return enriched


def _from_crossref(payload: dict[str, Any], abstract_limit: int) -> dict[str, Any]:
    authors = []
    for author in payload.get("author", []) or []:
        name = " ".join(
            part for part in (author.get("given", ""), author.get("family", "")) if part
        ).strip() or str(author.get("name", ""))
        if name:
            authors.append({"name": name, "orcid": _orcid_from(author.get("ORCID", ""))})
    issued = ((payload.get("issued", {}) or {}).get("date-parts") or [[]])[0]
    work_type = str(payload.get("type", "")).lower()
    container, container_server = _split_venue((payload.get("container-title") or [""])[0])
    if work_type == "posted-content":
        container_server = container_server or container or "Preprint"
        container = ""
    return _work_record(
        title=(payload.get("title") or [""])[0],
        abstract=payload.get("abstract", ""),
        abstract_limit=abstract_limit,
        keywords=payload.get("subject", []) or [],
        published_at=_date_parts(*(list(issued) + ["", ""])[:3]),
        doi=payload.get("DOI", ""),
        url=payload.get("URL", ""),
        venue=container,
        type="preprint" if work_type == "posted-content" else "article",
        preprint_server=container_server,
        authors=authors,
        source="crossref",
    )


def _orcid_from(value: str) -> str:
    match = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", str(value or ""), re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _enrich_via_crossref(
    client: SourceClient, sparse: list[dict[str, Any]], abstract_limit: int
) -> int:
    """Fill authors and metadata for any DOI, including work outside the life sciences.

    Europe PMC and PubMed only index biomedical literature, so Crossref is what gives
    statistics, computer science, and social science papers their coauthor lists.
    """

    targets = [work for work in sparse if work.get("doi")][:MAX_CROSSREF_LOOKUPS]
    enriched = 0
    for work in targets:
        try:
            response = client.get(
                f"{CROSSREF_API}/{work['doi']}",
                respect_robots=False,
                params={"mailto": CROSSREF_CONTACT},
            )
            payload = response.json().get("message", {})
        except (requests.RequestException, ValueError):
            continue
        if payload:
            _merge_into(work, _from_crossref(payload, abstract_limit))
            enriched += 1
    return enriched


def _enrich_via_preprint_server(
    client: SourceClient, sparse: list[dict[str, Any]], limit: int
) -> int:
    targets = [work for work in sparse if work.get("doi", "").startswith(PREPRINT_DOI_PREFIX)][:50]
    enriched = 0
    for work in targets:
        for server in ("medrxiv", "biorxiv"):
            try:
                response = client.get(f"{BIORXIV_API}/{server}/{work['doi']}", respect_robots=False)
                collection = response.json().get("collection", []) or []
            except (requests.RequestException, ValueError):
                continue
            if not collection:
                continue
            detail = collection[-1]
            authors = [
                {"name": name.strip()}
                for name in str(detail.get("authors", "")).split(";")
                if name.strip()
            ]
            _merge_into(
                work,
                _work_record(
                    title=detail.get("title", ""),
                    abstract=detail.get("abstract", ""),
                    abstract_limit=limit,
                    keywords=[detail.get("category", "")] if detail.get("category") else [],
                    published_at=_iso_date(detail.get("date", "")),
                    doi=work["doi"],
                    venue="",
                    type="preprint",
                    preprint_server="medRxiv" if server == "medrxiv" else "bioRxiv",
                    authors=authors,
                    source=server,
                ),
            )
            enriched += 1
            break
    return enriched


# --------------------------------------------------------------------------------------
# Per-researcher orchestration
# --------------------------------------------------------------------------------------

WORK_COLLECTORS = (
    ("europepmc", "Europe PMC", collect_europepmc_by_orcid),
    ("orcid", "ORCID record", collect_orcid_works),
    ("pubmed", "PubMed", collect_pubmed),
    ("arxiv", "arXiv", collect_arxiv),
)


def collect_researcher_works(
    client: SourceClient,
    researcher: dict[str, Any],
    organization: dict[str, Any],
    limits: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Gather one researcher's works from every source their profile supports."""

    collected: dict[str, dict[str, Any]] = {}
    health: list[dict[str, Any]] = []

    for source_type, label, collector in WORK_COLLECTORS:
        checked_at = _now()
        try:
            result = collector(client, researcher, limits)
        except PermissionError as error:
            result = WorksResult(status="blocked", message=clean_text(str(error), 300))
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
            ElementTree.ParseError,
        ) as error:
            result = WorksResult(status="error", message=clean_text(str(error), 300))

        for work in result.works:
            keys = work_keys(work)
            existing = next((collected[key] for key in keys if key in collected), None)
            merged = _merge_into(existing, work) if existing else work
            for key in work_keys(merged):
                collected[key] = merged

        health.append(
            {
                "source_id": f"{organization['id']}:{researcher['id']}:{source_type}",
                "organization_id": organization["id"],
                "researcher_id": researcher["id"],
                "researcher_name": researcher.get("full_name", ""),
                "source_type": f"works_{source_type}",
                "source_label": f"{label} · {researcher.get('full_name', '')}",
                "status": result.status,
                "message": result.message,
                "items_found": len(result.works),
                "checked_at": checked_at,
            }
        )

    works = list({id(work): work for work in collected.values()}.values())
    for work in works:
        work["researcher_ids"] = [researcher["id"]]
        work["organization_ids"] = [organization["id"]]
    return works, health


def enrich_works(
    client: SourceClient, works: list[dict[str, Any]], abstract_limit: int
) -> dict[str, int]:
    """Fill in abstracts, keywords, and coauthors that the primary sources left out.

    Runs once over the deduplicated set so a paper shared by ten coauthors costs one
    lookup instead of ten. Each stage only sees what the previous stage could not fill.
    """

    counts = {}
    missing_abstract = [work for work in works if not work["abstract"]]
    counts["europepmc"] = _enrich_via_europepmc(client, missing_abstract, abstract_limit)
    counts["arxiv"] = _enrich_via_arxiv(
        client, [work for work in missing_abstract if not work["abstract"]], abstract_limit
    )
    counts["preprint_server"] = _enrich_via_preprint_server(
        client, [work for work in missing_abstract if not work["abstract"]], abstract_limit
    )
    counts["crossref"] = _enrich_via_crossref(
        client,
        [work for work in works if not work["abstract"] or not work["authors"]],
        abstract_limit,
    )
    return counts


# --------------------------------------------------------------------------------------
# Snapshot assembly
# --------------------------------------------------------------------------------------


def _merge_works_history(
    new_works: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
    generated_at: str,
    retention_years: int,
    max_per_researcher: int,
) -> list[dict[str, Any]]:
    """Merge this run into bounded history so a flaky source never drops a paper."""

    merged: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for previous in (previous_snapshot or {}).get("works", []):
        # Re-apply the current rules so records kept by an older run cannot outlive them.
        if not previous.get("id") or not is_citable(previous):
            continue
        record = dict(previous)
        merged[record["id"]] = record
        for key in work_keys(record):
            by_key.setdefault(key, record)

    for work in new_works:
        existing = next((by_key[key] for key in work_keys(work) if key in by_key), None)
        if existing:
            work["id"] = existing["id"]
            work["first_seen_at"] = existing.get("first_seen_at", generated_at)
            # Carry forward anything an earlier run enriched that this one did not reach,
            # so a capped or unavailable enrichment source never regresses a record.
            _merge_into(work, existing)
        else:
            work["id"] = _work_id(work)
            work["first_seen_at"] = generated_at
        work["last_seen_at"] = generated_at
        merged[work["id"]] = work
        for key in work_keys(work):
            by_key[key] = work

    cutoff = (datetime.fromisoformat(generated_at) - timedelta(days=365 * retention_years)).year
    retained = [work for work in merged.values() if not work.get("year") or work["year"] >= cutoff]

    # Cap per researcher rather than globally so no center crowds out another. A shared
    # work survives when it is recent enough for any one of its authors.
    by_researcher: dict[str, list[dict[str, Any]]] = {}
    for work in retained:
        for researcher_id in work.get("researcher_ids", []) or ["__unattributed__"]:
            by_researcher.setdefault(researcher_id, []).append(work)

    keep: set[str] = set()
    for works in by_researcher.values():
        works.sort(
            key=lambda work: (work.get("published_at", ""), work.get("title", "")), reverse=True
        )
        keep.update(work["id"] for work in works[:max_per_researcher])

    return sorted(
        (work for work in retained if work["id"] in keep),
        key=lambda work: (work.get("published_at", ""), work.get("title", "")),
        reverse=True,
    )


def build_works_snapshot(
    profiles: dict[str, Any],
    client: SourceClient | None = None,
    previous_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect works for every researcher, isolating individual source failures."""

    client = client or SourceClient()
    generated_at = _now()
    network = profiles.get("network", {})
    limits = {
        "max_works": int(network.get("max_works_per_researcher", 100)),
        "abstract_limit": int(network.get("abstract_max_chars", 1500)),
    }

    by_key: dict[str, dict[str, Any]] = {}
    health: list[dict[str, Any]] = []
    for organization in profiles.get("organizations", []):
        for researcher in organization.get("researchers", []):
            if not researcher.get("collect_works", True):
                continue
            works, researcher_health = collect_researcher_works(
                client, researcher, organization, limits
            )
            health.extend(researcher_health)
            for work in works:
                existing = next((by_key[key] for key in work_keys(work) if key in by_key), None)
                if existing:
                    _merge_into(existing, work)
                    existing["researcher_ids"] = list(
                        dict.fromkeys(existing["researcher_ids"] + work["researcher_ids"])
                    )
                    existing["organization_ids"] = list(
                        dict.fromkeys(existing["organization_ids"] + work["organization_ids"])
                    )
                    work = existing
                for key in work_keys(work):
                    by_key[key] = work

    collected = [
        work for work in {id(work): work for work in by_key.values()}.values() if is_citable(work)
    ]
    enrichment = enrich_works(client, collected, limits["abstract_limit"])
    for work in collected:
        _finalize_type(work)

    works = _merge_works_history(
        collected,
        previous_snapshot,
        generated_at,
        int(network.get("works_retention_years", 15)),
        limits["max_works"],
    )

    researcher_counts: dict[str, int] = {}
    for work in works:
        for researcher_id in work.get("researcher_ids", []):
            researcher_counts[researcher_id] = researcher_counts.get(researcher_id, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "stats": {
            "works": len(works),
            "preprints": sum(work.get("type") == "preprint" for work in works),
            "with_abstract": sum(bool(work.get("abstract")) for work in works),
            "with_doi": sum(bool(work.get("doi")) for work in works),
            "with_pmid": sum(bool(work.get("pmid")) for work in works),
            "researchers_with_works": len(researcher_counts),
            "sources_ok": sum(row["status"] == "ok" for row in health),
            "sources_attention": sum(row["status"] in {"error", "blocked"} for row in health),
        },
        "enrichment": enrichment,
        "works_per_researcher": researcher_counts,
        "works": works,
        "health": health,
    }
