"""Search the ORCID registry by name and keep records that match a center's institutions.

Scaffolding only — see README.md. Useful for people OpenAlex cannot resolve, which is
most staff, students, and anyone with few indexed publications.

Writes `.scaffold/orcid_search.json` and prints the hits.
"""

from __future__ import annotations

import json
import time
import urllib.parse

import common


def search(query: str) -> dict:
    url = (
        "https://pub.orcid.org/v3.0/expanded-search/?q="
        + urllib.parse.quote(query)
        + "&rows=50"
    )
    payload = common.get_json(url)
    return {} if "__error__" in payload else payload


def main() -> None:
    decisions_path = common.out_path("decisions.json")
    decided = json.loads(decisions_path.read_text()) if decisions_path.exists() else {}

    results = {}
    for person in common.load_people():
        key = f"{person['org_id']}/{person['id']}"
        if decided.get(key, {}).get("orcid") or person["existing"].get("orcid"):
            continue
        parts = person["search_name"].split()
        payload = search(f'given-names:"{parts[0]}" AND family-name:"{parts[-1]}"')
        hints = common.expected_institutions(person)

        hits = []
        for row in payload.get("expanded-result") or []:
            institutions = row.get("institution-name") or []
            matched = common.institution_hits(" ".join(institutions), hints)
            if matched:
                hits.append(
                    {
                        "orcid": row["orcid-id"],
                        "name": f"{row.get('given-names')} {row.get('family-names')}",
                        "institutions": institutions[:8],
                        "matched": matched,
                    }
                )

        results[key] = {
            "name": person["full_name"],
            "total_name_matches": payload.get("num-found", 0),
            "hits": hits,
        }
        if hits:
            print(f"{key} ({person['full_name']}) total={payload.get('num-found')}")
            for hit in hits:
                print(f"   {hit['orcid']}  {hit['name']}  {hit['institutions']}")
        time.sleep(0.25)

    path = common.out_path("orcid_search.json")
    path.write_text(json.dumps(results, indent=1))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
