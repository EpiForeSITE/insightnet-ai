# Ask InsightNet service. The retrieval index is copied into the image, so a cold start
# does no network I/O to load it and the container can never answer from an index that
# does not match the code it shipped with.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Dependencies first: this layer is cached until pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --extra server --no-install-project

COPY insightnet/ ./insightnet/
COPY server/ ./server/
COPY data/rag/ ./data/rag/

RUN uv sync --locked --no-dev --extra server

EXPOSE 8080
CMD ["sh", "-c", "uv run --no-sync uvicorn server.main:create_app --factory --host 0.0.0.0 --port ${PORT}"]
