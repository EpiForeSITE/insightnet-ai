"""Print the full evidence behind ORCID records for rare names.

Scaffolding only — see README.md. When only a handful of ORCID records share a
researcher's name, this dumps employments, education, work titles, and self-reported
URLs so the record can be confirmed or rejected.

An ORCID record with no employments and no works proves nothing, however rare the
name — reject those rather than guessing.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse

import common

MAX_NAMESAKES = 3


def main() -> None:
    path = common.out_path("orcid_search.json")
    if not path.exists():
        sys.exit(f"{path} not found — run orcid_search.py first")
    searched = json.loads(path.read_text())
    people = {f"{p['org_id']}/{p['id']}": p for p in common.load_people()}

    for key, entry in searched.items():
        total = entry["total_name_matches"]
        if entry["hits"] or not 0 < total <= MAX_NAMESAKES:
            continue
        person = people[key]
        parts = person["search_name"].split()
        query = f'given-names:"{parts[0]}" AND family-name:"{parts[-1]}"'
        payload = common.get_json(
            "https://pub.orcid.org/v3.0/expanded-search/?q=" + urllib.parse.quote(query) + "&rows=5"
        )
        print(f"\n### {key}  {person['full_name']}  [{person['role'][:70]}]")
        for row in payload.get("expanded-result") or []:
            orcid_id = row["orcid-id"]
            record = common.get_json(f"https://pub.orcid.org/v3.0/{orcid_id}/record")
            name = (record.get("person") or {}).get("name") or {}
            given = (name.get("given-names") or {}).get("value")
            family = (name.get("family-name") or {}).get("value")
            print(f"  {orcid_id}  {given} {family}")

            activities = record.get("activities-summary") or {}
            for section in ("employments", "educations"):
                for group in (activities.get(section) or {}).get("affiliation-group", [])[:4]:
                    for summary in group.get("summaries", []):
                        item = next(iter(summary.values()))
                        organization = (item.get("organization") or {}).get("name", "")
                        print(f"      {section[:3]}: {organization} | {item.get('role-title')}")
            for work in (activities.get("works") or {}).get("group", [])[:3]:
                title = (work["work-summary"][0].get("title") or {}).get("title", {}).get("value", "")
                print(f"      work: {title[:90]}")
            for url in ((record.get("person") or {}).get("researcher-urls") or {}).get(
                "researcher-url", []
            ):
                print(f"      url: {url.get('url-name')} {(url.get('url') or {}).get('value')}")
            time.sleep(0.2)


if __name__ == "__main__":
    main()
