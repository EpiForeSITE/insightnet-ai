"""Runtime settings for the Ask InsightNet service.

Every limit and price is an environment variable so it can be changed with
``gcloud run services update`` rather than a rebuild. Prices in particular move, and a
price change should never require a code review.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ORIGINS = "https://epiforesite.github.io"


def _text(name: str, default: str) -> str:
    """Read a variable, treating unset and empty as the same thing.

    ``gcloud run deploy --set-env-vars`` renders an unset GitHub Actions variable as an
    empty value rather than omitting it, so ``os.getenv(name, default)`` would return ""
    and skip the default. For the CORS allowlist that turns a forgotten repository
    variable into an empty allowlist, which rejects every browser request on the live
    site — a deploy that succeeds and then serves 403 to everyone.
    """

    return os.getenv(name, "").strip() or default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    project: str = ""
    location: str = "us-central1"
    model: str = "gemini-2.5-flash-lite"
    embed_model: str = "gemini-embedding-001"
    embed_dims: int = 256
    index_dir: Path = Path("data/rag")
    environment: str = "production"

    allowed_origins: tuple[str, ...] = (DEFAULT_ORIGINS,)
    max_body_bytes: int = 2048
    min_question_chars: int = 3
    max_question_chars: int = 300

    ip_minute_limit: int = 5
    ip_day_limit: int = 40
    daily_query_cap: int = 400
    monthly_budget_micros: int = 5_000_000

    price_in_micros_per_mtok: int = 100_000
    price_out_micros_per_mtok: int = 400_000

    max_output_tokens: int = 512
    temperature: float = 0.2
    cache_ttl_days: int = 7
    ip_salt: str = "insightnet"

    @classmethod
    def from_env(cls) -> Settings:
        origins = _text("ALLOWED_ORIGINS", DEFAULT_ORIGINS)
        environment = _text("ENVIRONMENT", "production")
        allowed = tuple(o.strip() for o in origins.split(",") if o.strip())
        if environment == "dev":
            allowed += ("http://localhost:8000", "http://127.0.0.1:8000")
        return cls(
            project=_text("GOOGLE_CLOUD_PROJECT", ""),
            location=_text("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model=_text("INSIGHTNET_MODEL", "gemini-2.5-flash-lite"),
            embed_model=_text("INSIGHTNET_EMBED_MODEL", "gemini-embedding-001"),
            embed_dims=_int("INSIGHTNET_EMBED_DIMS", 256),
            index_dir=Path(_text("INSIGHTNET_INDEX_DIR", "data/rag")),
            environment=environment,
            allowed_origins=allowed,
            ip_minute_limit=_int("IP_MINUTE_LIMIT", 5),
            ip_day_limit=_int("IP_DAY_LIMIT", 40),
            daily_query_cap=_int("DAILY_QUERY_CAP", 400),
            monthly_budget_micros=_int("MONTHLY_BUDGET_MICROS", 5_000_000),
            price_in_micros_per_mtok=_int("PRICE_IN_MICROS_PER_MTOK", 100_000),
            price_out_micros_per_mtok=_int("PRICE_OUT_MICROS_PER_MTOK", 400_000),
            max_output_tokens=_int("MAX_OUTPUT_TOKENS", 512),
            cache_ttl_days=_int("CACHE_TTL_DAYS", 7),
            ip_salt=_text("IP_SALT", "insightnet"),
        )
