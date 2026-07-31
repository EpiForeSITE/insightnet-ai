"""Shared helpers for the profile scaffolding scripts.

Scaffolding only — see README.md. Nothing here runs in the daily refresh.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import time
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(os.environ.get("INSIGHTNET_SCAFFOLD_DIR", ROOT / ".scaffold"))
USER_AGENT = "InsightNetProfileScaffold/1.0 (+https://insightnet.us/)"

# Institutions a center's people plausibly belong to, used to score candidates.
ORG_INSTITUTIONS = {
    "accidda": ["north carolina", "johns hopkins", "unc"],
    "c-core": ["kaiser", "berkeley", "california, san francisco", "ucsf"],
    "cidmath": ["emory"],
    "cori": ["johns hopkins"],
    "delphi": ["carnegie mellon", "british columbia"],
    "dma-prime": ["clemson"],
    "epiengage": ["texas at austin", "massachusetts", "london school", "georgia"],
    "epistorm": [
        "northeastern", "boston university", "indiana university", "los alamos",
        "california, san diego", "florida", "virginia", "fred hutch", "washington",
    ],
    "foresite": ["utah", "washington state", "veterans affairs", "intermountain"],
    "madmc": ["minnesota", "washington", "tulane", "brown"],
    "micom": ["michigan"],
    "resilient-shield": ["california, san diego", "san diego"],
    "soar": ["oregon"],
}

PROFILE_FIELDS = (
    "website",
    "linkedin",
    "github",
    "twitter",
    "bluesky",
    "google_scholar",
    "orcid",
)


def get_json(url: str, accept: str = "application/json", tries: int = 3) -> dict[str, Any]:
    """Fetch JSON via curl; some sandboxes break Python's TLS chain but not curl's."""
    for attempt in range(tries):
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "30", "-H", f"Accept: {accept}", "-A", USER_AGENT, url],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                if attempt == tries - 1:
                    return {"__error__": f"bad json: {exc}"}
        elif attempt == tries - 1:
            return {"__error__": proc.stderr.strip()[:200] or "empty response"}
        time.sleep(1.5 * (attempt + 1))
    return {"__error__": "unreachable"}


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z ]", "", (text or "").lower())


def name_tokens(name: str) -> list[str]:
    return [token for token in norm(name).split() if len(token) > 1]


def name_match(left: str, right: str) -> bool:
    """True when first and last name agree, ignoring middle names and initials."""
    a, b = name_tokens(left), name_tokens(right)
    return bool(a and b and a[0] == b[0] and a[-1] == b[-1])


def search_name(full_name: str) -> str:
    """Strip degrees and nicknames so the name can be used as a search query."""
    name = re.sub(r",\s*(PhD|MD|MBA|MPH|MS|DPhil|BDS|DrPH|ScD|PharmD|RN)\b\.?", "", full_name)
    name = re.sub(r"\(([^)]*)\)", "", name)
    return re.sub(r"\s+", " ", name).strip().strip(",")


def expected_institutions(person: dict[str, Any]) -> list[str]:
    """Institution hints for a researcher: their center's, plus any named in their role."""
    hints = list(ORG_INSTITUTIONS.get(person["org_id"], []))
    for phrase in re.findall(r"[a-z ]+", norm(person.get("role"))):
        phrase = phrase.strip()
        if len(phrase) > 5 and any(word in phrase for word in ("universi", "institut", "school")):
            hints.append(phrase)
    return hints


def institution_hits(blob: str, hints: list[str]) -> list[str]:
    normalized = norm(blob)
    return [hint for hint in hints if hint in normalized]


def load_people() -> list[dict[str, Any]]:
    """Flatten every researcher in config/organizations into a list with center context."""
    people = []
    for path in sorted((ROOT / "config/organizations").glob("*.toml")):
        org = tomllib.load(path.open("rb"))["organization"]
        for person in org.get("researchers", []):
            people.append(
                {
                    "org_id": org["id"],
                    "org_name": org["name"],
                    "id": person.get("id", ""),
                    "full_name": person["full_name"],
                    "search_name": search_name(person["full_name"]),
                    "role": person.get("role", ""),
                    "bio": person.get("bio", ""),
                    "existing": {f: person[f] for f in PROFILE_FIELDS if person.get(f)},
                }
            )
    return people


def out_path(name: str) -> pathlib.Path:
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT / name
