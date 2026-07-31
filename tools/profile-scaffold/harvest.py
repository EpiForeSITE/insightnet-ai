"""Gather candidate identifiers for every researcher from public APIs.

Scaffolding only — see README.md. Writes candidates plus their evidence to
`.scaffold/harvest.json` for a human to review with `review.py`.

Run sequentially. OpenAlex meters requests against a daily budget and returns
empty result sets once it is exhausted, which is easy to mistake for "no match".
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any

import common

MAILTO = "insightnet@example.org"  # OpenAlex polite pool; use a real address


def openalex(name: str) -> dict[str, Any]:
    url = (
        "https://api.openalex.org/authors?search="
        + urllib.parse.quote(name)
        + f"&per_page=5&mailto={MAILTO}"
    )
    payload = common.get_json(url)
    if "__error__" in payload:
        return {"error": payload["__error__"]}
    if payload.get("error"):
        return {"error": payload["error"]}
    candidates = []
    for author in payload.get("results", []):
        affiliations = []
        for affiliation in author.get("affiliations", [])[:6]:
            institution = (affiliation.get("institution") or {}).get("display_name")
            years = affiliation.get("years", [])
            if institution:
                affiliations.append(
                    f"{institution} ({min(years)}-{max(years)})" if years else institution
                )
        candidates.append(
            {
                "name": author.get("display_name", ""),
                "orcid": (author.get("orcid") or "").rsplit("/", 1)[-1],
                "works": author.get("works_count", 0),
                "cited": author.get("cited_by_count", 0),
                "last_institutions": [
                    i.get("display_name") for i in (author.get("last_known_institutions") or [])
                ],
                "affiliations": affiliations,
                "topics": [t["display_name"] for t in author.get("topics", [])[:5]],
            }
        )
    return {"candidates": candidates}


def orcid_person(orcid_id: str) -> dict[str, Any]:
    """Self-reported links and employment history — the strongest evidence available."""
    payload = common.get_json(f"https://pub.orcid.org/v3.0/{orcid_id}/person")
    if "__error__" in payload:
        return {"error": payload["__error__"]}
    record: dict[str, Any] = {"urls": [], "employments": []}
    for item in (payload.get("researcher-urls") or {}).get("researcher-url", []) or []:
        record["urls"].append(
            [item.get("url-name") or "", (item.get("url") or {}).get("value", "")]
        )
    employments = common.get_json(f"https://pub.orcid.org/v3.0/{orcid_id}/employments")
    for group in (employments.get("affiliation-group") or []):
        for summary in group.get("summaries", []) or []:
            item = summary.get("employment-summary", {})
            organization = (item.get("organization") or {}).get("name", "")
            start = ((item.get("start-date") or {}).get("year") or {}).get("value", "")
            record["employments"].append(
                f"{organization} — {item.get('role-title') or ''} ({start})".strip()
            )
    return record


def bluesky(name: str) -> dict[str, Any]:
    url = (
        "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors?q="
        + urllib.parse.quote(name)
        + "&limit=6"
    )
    payload = common.get_json(url)
    if "__error__" in payload:
        return {"error": payload["__error__"]}
    return {
        "candidates": [
            {
                "handle": actor.get("handle", ""),
                "display": actor.get("displayName", ""),
                "description": (actor.get("description") or "").replace("\n", " ")[:280],
            }
            for actor in payload.get("actors", [])
        ]
    }


def main() -> None:
    people = common.load_people()
    results = []
    for index, person in enumerate(people, 1):
        entry = dict(person)
        entry["openalex"] = openalex(person["search_name"])
        time.sleep(0.2)
        entry["bluesky"] = bluesky(person["search_name"])
        time.sleep(0.2)
        entry["orcid_records"] = {}
        for candidate in entry["openalex"].get("candidates", []):
            orcid_id = candidate["orcid"]
            if orcid_id and orcid_id not in entry["orcid_records"]:
                entry["orcid_records"][orcid_id] = orcid_person(orcid_id)
                time.sleep(0.2)
        results.append(entry)
        found = len(entry["openalex"].get("candidates", []))
        print(f"{index}/{len(people)} {person['full_name']}: {found} author candidates", flush=True)
        if entry["openalex"].get("error"):
            print(f"  OpenAlex error: {entry['openalex']['error']}", flush=True)

    path = common.out_path("harvest.json")
    path.write_text(json.dumps(results, indent=1))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
