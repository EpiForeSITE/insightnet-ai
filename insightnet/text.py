"""Small, deterministic text helpers used by collection and search."""

from __future__ import annotations

import html
import re
from collections import Counter
from collections.abc import Iterable

STOP_WORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "are",
    "been",
    "being",
    "center",
    "centre",
    "for",
    "from",
    "have",
    "into",
    "more",
    "network",
    "new",
    "our",
    "research",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "using",
    "was",
    "were",
    "with",
}


def clean_text(value: str, limit: int | None = None) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        return value[: limit - 1].rstrip() + "…"
    return value


def extract_keywords(
    parts: Iterable[str], configured: Iterable[str] = (), limit: int = 12
) -> list[str]:
    configured_clean = [clean_text(item).lower() for item in configured if clean_text(item)]
    words: list[str] = []
    for part in parts:
        words.extend(re.findall(r"[a-z][a-z0-9-]{2,}", clean_text(part).lower()))
    counts = Counter(word for word in words if word not in STOP_WORDS)
    ranked = [word for word, _ in counts.most_common(limit)]
    return list(dict.fromkeys(configured_clean + ranked))[:limit]
