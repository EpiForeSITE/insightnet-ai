"""Compact, reviewable view of the harvest.

Scaffolding only — see README.md. Prints only candidates whose name matches and whose
affiliations tie back to the researcher's center, together with the evidence, so a
person can accept or reject each one.

Usage: python tools/profile-scaffold/review.py [org_id ...]
"""

from __future__ import annotations

import json
import sys

import common


def main() -> None:
    path = common.out_path("harvest.json")
    if not path.exists():
        sys.exit(f"{path} not found — run harvest.py first")
    people = json.loads(path.read_text())
    wanted = set(sys.argv[1:])

    for person in sorted(people, key=lambda p: (p["org_id"], p["id"])):
        if wanted and person["org_id"] not in wanted:
            continue
        hints = common.expected_institutions(person)

        authors = []
        for candidate in person.get("openalex", {}).get("candidates", []):
            orcid_id = candidate["orcid"]
            if not orcid_id or not common.name_match(person["search_name"], candidate["name"]):
                continue
            record = person.get("orcid_records", {}).get(orcid_id, {})
            employments = record.get("employments", [])[:3]
            hits = common.institution_hits(
                " ".join(candidate["last_institutions"] + candidate["affiliations"]), hints
            )
            if hits or common.institution_hits(" ".join(employments), hints):
                authors.append((orcid_id, candidate, hits, employments, record.get("urls", [])))

        actors = [
            actor
            for actor in person.get("bluesky", {}).get("candidates", [])
            if common.name_match(person["search_name"], actor["display"] or "")
        ]

        header = f"- {person['org_id']}/{person['id']}  {person['full_name']}"
        if not authors and not actors:
            print(f"{header}  ::  nothing to review")
            continue
        print(f"{header}  [{person['role'][:60]}]")
        if person["existing"]:
            print(f"    already recorded: {sorted(person['existing'])}")
        for orcid_id, candidate, hits, employments, urls in authors[:2]:
            print(
                f"    ORCID {orcid_id} as {candidate['name']!r} "
                f"works={candidate['works']} institution_match={hits}"
            )
            if employments:
                print(f"      employment: {' | '.join(employments)}")
            if urls:
                print(f"      self-reported urls: {urls}")
        for actor in actors[:2]:
            print(f"    BLUESKY @{actor['handle']} ({actor['display']}) :: {actor['description'][:170]}")


if __name__ == "__main__":
    main()
