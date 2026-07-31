"""Merge adjudicated links into `.scaffold/decisions.json`.

Scaffolding only — see README.md. Reads JSON on stdin so decisions can be recorded in
small batches as they are verified. Bare ORCID iDs, Scholar user ids, and handles are
expanded into full URLs.

    python tools/profile-scaffold/record.py <<'JSON'
    {"foresite/some-person": {"orcid": "0000-0002-1825-0097",
                              "google_scholar": "d4bTy4kAAAAJ",
                              "bluesky": "someone.bsky.social",
                              "website": "https://example.org"}}
    JSON

Pass an empty string to drop a field that was recorded by mistake.
"""

from __future__ import annotations

import json
import sys

import common


def normalize(field: str, value: str) -> str:
    value = value.strip()
    if not value or value.startswith("http"):
        return value
    if field == "orcid":
        return f"https://orcid.org/{value}"
    if field == "google_scholar":
        return f"https://scholar.google.com/citations?user={value}&hl=en"
    if field == "bluesky":
        return f"https://bsky.app/profile/{value}"
    if field == "twitter":
        return f"https://x.com/{value.lstrip('@')}"
    return value


def main() -> None:
    path = common.out_path("decisions.json")
    store = json.loads(path.read_text()) if path.exists() else {}

    for key, fields in json.load(sys.stdin).items():
        entry = store.setdefault(key, {})
        for field, value in fields.items():
            if field not in common.PROFILE_FIELDS:
                sys.exit(f"unknown profile field {field!r} for {key}")
            normalized = normalize(field, value)
            if normalized:
                entry[field] = normalized
            else:
                entry.pop(field, None)

    path.write_text(json.dumps(store, indent=1, sort_keys=True))
    total = sum(len(fields) for fields in store.values())
    print(f"{len(store)} researchers, {total} links recorded in {path}")


if __name__ == "__main__":
    main()
