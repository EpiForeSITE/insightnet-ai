"""The Ask InsightNet service.

One endpoint, ``POST /ask``, which retrieves from the committed index and streams a
grounded answer. The index is baked into the container image, so a cold start does no
network I/O to load it.

There is no API key anywhere: Vertex AI is reached through Application Default
Credentials, which on Cloud Run means the service account itself.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from insightnet import rag
from server import prompts
from server.budget import Guard, MemoryLedger
from server.config import Settings

logger = logging.getLogger("insightnet.ask")


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


#: ``generator(system, user)`` yields text fragments and finally a :class:`Usage`.
Generator = Callable[[str, str], Iterator[Any]]


class Lazy:
    """Build an upstream client on first use rather than at startup.

    Constructing the Vertex client resolves Application Default Credentials, which fails
    if the metadata server is unreachable. Doing that during startup would make a
    credentials problem look like a crash loop: the revision never becomes healthy and
    Cloud Run reports only that the container failed to listen. Deferring it means the
    container always starts, ``/readyz`` reports the truth about the index, and a
    credentials failure surfaces as a clean 503 on ``/ask`` with a keyword fallback.
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._value: Any = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._value is None:
            self._value = self._factory()
        return self._value(*args, **kwargs)


def vertex_generator(settings: Settings) -> Generator:
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True, project=settings.project or None, location=settings.location
    )

    def generate(system: str, user: str) -> Iterator[Any]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=settings.temperature,
            max_output_tokens=settings.max_output_tokens,
            # Gemini 2.5 models think by default and bill thinking at the output rate.
            # Leaving this unset roughly triples the cost of every answer.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        usage = Usage()
        for chunk in client.models.generate_content_stream(
            model=settings.model, contents=user, config=config
        ):
            if chunk.text:
                yield chunk.text
            metadata = getattr(chunk, "usage_metadata", None)
            if metadata:
                usage = Usage(
                    input_tokens=metadata.prompt_token_count or 0,
                    # Thinking tokens are billed as output, so they must be charged.
                    output_tokens=(metadata.candidates_token_count or 0)
                    + (getattr(metadata, "thoughts_token_count", 0) or 0),
                )
        yield usage

    return generate


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_app(
    settings: Settings | None = None,
    index: rag.Index | None = None,
    guard: Guard | None = None,
    generator: Generator | None = None,
    embedder: rag.Embedder | None = None,
) -> FastAPI:
    """Build the app.

    Every collaborator is injectable so the tests can run the whole request path with no
    credentials, no Firestore, and no model.
    """

    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Only the collaborators that were not injected are built here: loading the
        # index off disk and opening the Vertex client are the slow, failure-prone
        # steps, and they are exactly what production needs and tests do not.
        state = app.state
        if getattr(state, "index", None) is None:
            state.index = rag.Index.load(settings.index_dir)
        if getattr(state, "guard", None) is None:
            state.guard = Guard(settings, _default_ledger(settings))
        if getattr(state, "generator", None) is None:
            state.generator = Lazy(lambda: vertex_generator(settings))
        if getattr(state, "embedder", None) is None:
            state.embedder = Lazy(
                lambda: rag.vertex_embedder(
                    model=settings.embed_model,
                    dims=settings.embed_dims,
                    location=settings.location,
                )
            )
        if settings.environment != "dev" and settings.ip_salt == Settings().ip_salt:
            # The default is published in this repository, so anyone could hash the IPv4
            # space and recover the addresses behind the rate-limit counters.
            logger.warning("IP_SALT is unset; rate-limit hashes are not private")
        state.ready = True
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.index = index
    app.state.guard = guard
    app.state.generator = generator
    app.state.embedder = embedder
    # A fully-injected app is usable without the lifespan having run, which is what lets
    # the tests exercise the real request path directly.
    app.state.ready = all(x is not None for x in (index, guard, generator, embedder))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["content-type"],
        max_age=86400,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        ready = getattr(request.app.state, "ready", False)
        index = getattr(request.app.state, "index", None)
        return JSONResponse(
            {
                "ready": bool(ready and index),
                "chunks": len(index.chunks) if index else 0,
                "indexGeneratedAt": index.manifest.get("generated_at", "") if index else "",
            },
            status_code=200 if ready and index else 503,
        )

    @app.post("/ask")
    async def ask(request: Request) -> Any:
        state = request.app.state
        settings: Settings = state.settings

        origin = request.headers.get("origin")
        # A missing Origin is allowed so curl and server-side probes work; it is trivially
        # forged anyway, which is why the rate limits below are the real perimeter.
        if origin and origin not in settings.allowed_origins:
            return JSONResponse({"error": "forbidden_origin"}, status_code=403)

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_body_bytes:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
        raw = await request.body()
        if len(raw) > settings.max_body_bytes:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)

        try:
            payload = json.loads(raw or b"{}")
            question = str(payload["question"]).strip()
        except (json.JSONDecodeError, KeyError, TypeError):
            return JSONResponse(
                {"error": "bad_request", "detail": "expected a JSON body with a question"},
                status_code=400,
            )
        if not settings.min_question_chars <= len(question) <= settings.max_question_chars:
            return JSONResponse(
                {
                    "error": "bad_request",
                    "detail": f"question must be {settings.min_question_chars}"
                    f"-{settings.max_question_chars} characters",
                },
                status_code=422,
            )

        denial = state.guard.check(_client_address(request))
        if denial is not None:
            return JSONResponse(denial.body, status_code=denial.status)

        index: rag.Index = state.index
        generated_at = index.manifest.get("generated_at", "")
        key = state.guard.cache_key(question, generated_at)
        hit = state.guard.cached(key)
        if hit:
            return StreamingResponse(
                _replay(hit), media_type="text/event-stream", headers=_stream_headers()
            )

        try:
            vector = rag.embed_query(state.embedder, question)
        except Exception:
            logger.exception("query embedding failed")
            return JSONResponse(
                {"error": "upstream_unavailable", "fallback": "keyword"}, status_code=503
            )

        retrieval = rag.search(index, question, vector)
        if not retrieval.confident:
            return JSONResponse({"answer": None, "reason": retrieval.reason or "no_match"})

        meta = {
            # Every document the prompt offers, because the client drops markers it does
            # not recognise. People and tools are citable too — an answer naming the
            # center that builds a dashboard cites `t:respilens`, not a paper — and
            # listing only works would silently strip those correct citations.
            "citations": _citable(retrieval),
            "researchers": [
                {k: r[k] for k in ("id", "name", "role", "organization_ids", "score", "evidence")}
                for r in retrieval.researchers
            ],
            "tools": retrieval.tools,
            "organizations": retrieval.organizations,
            "indexGeneratedAt": generated_at,
            "spread": retrieval.spread,
            "cached": False,
        }
        return StreamingResponse(
            _stream(state, settings, question, retrieval, meta, key),
            media_type="text/event-stream",
            headers=_stream_headers(),
        )

    return app


def _citable(retrieval: rag.Retrieval) -> list[dict[str, Any]]:
    """Every document the prompt shows the model, in the shape the client renders."""

    documents = [{**citation, "kind": "work"} for citation in retrieval.citations]
    documents += [
        {
            "id": f"r:{researcher['id']}",
            "kind": "researcher",
            "title": researcher["name"],
            "subtitle": researcher.get("role", ""),
            "organization_ids": researcher.get("organization_ids", []),
        }
        for researcher in retrieval.researchers
    ]
    documents += [
        {
            "id": tool["id"],
            "kind": "tool",
            "title": tool["title"],
            "subtitle": "; ".join(tool.get("organization_names") or []),
            "url": tool.get("url", ""),
        }
        for tool in retrieval.tools
    ]
    documents += [
        {
            "id": f"o:{center['id']}",
            "kind": "center",
            "title": center["name"],
            "url": center.get("url", ""),
        }
        for center in retrieval.organizations
    ]
    return documents


def _stream_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def _client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _replay(payload: dict[str, Any]) -> Iterator[str]:
    meta = dict(payload.get("meta") or {})
    meta["cached"] = True
    yield sse("meta", meta)
    yield sse("token", {"t": payload.get("answer", "")})
    yield sse("done", {"inputTokens": 0, "outputTokens": 0, "cached": True})


def _stream(
    state: Any,
    settings: Settings,
    question: str,
    retrieval: rag.Retrieval,
    meta: dict[str, Any],
    key: str,
) -> Iterator[str]:
    """Emit ``meta`` first so citation cards render while the prose is still arriving."""

    yield sse("meta", meta)
    prompt = prompts.build_prompt(question, retrieval)
    answer: list[str] = []
    usage = Usage()
    # Because no score threshold reliably separates answerable questions from noise
    # (see rag.RELEVANCE_IS_THE_MODELS_JOB), the model is what decides, by replying with
    # the refusal sentinel. It always leads the response, so holding back just enough
    # characters to recognise it keeps the refusal off the screen without costing any
    # perceptible streaming latency.
    held = True
    try:
        for piece in state.generator(prompts.SYSTEM_INSTRUCTION, prompt):
            if isinstance(piece, Usage):
                usage = piece
                continue
            answer.append(piece)
            if held:
                pending = "".join(answer).lstrip()
                if prompts.NO_MATCH.startswith(pending[: len(prompts.NO_MATCH)]):
                    continue  # still might be a refusal; keep buffering
                held = False
                yield sse("token", {"t": "".join(answer)})
            else:
                yield sse("token", {"t": piece})
    except Exception:
        logger.exception("generation failed")
        yield sse("error", {"error": "upstream_unavailable", "fallback": "keyword"})
        return

    text = "".join(answer).strip()
    state.guard.record_spend(usage.input_tokens, usage.output_tokens)
    if not text or prompts.NO_MATCH in text:
        yield sse("no_match", {"answer": None, "reason": "no_confident_match"})
        yield sse("done", {"inputTokens": usage.input_tokens, "outputTokens": usage.output_tokens})
        return
    if held:  # short answer that never cleared the buffer
        yield sse("token", {"t": text})
    state.guard.remember(key, {"meta": meta, "answer": text})
    yield sse("done", {"inputTokens": usage.input_tokens, "outputTokens": usage.output_tokens})


def _default_ledger(settings: Settings):
    if settings.environment == "dev":
        return MemoryLedger()
    from server.budget import FirestoreLedger

    return FirestoreLedger(settings.project)


