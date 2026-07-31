"""Write verified links from `.scaffold/decisions.json` into the TOML profiles.

Scaffolding only — see README.md. This is a one-way bootstrap: after the initial pass,
edit `config/organizations/*.toml` by hand.

A value already present in a profile is never overwritten, so a stale decisions file
cannot clobber curated links. New keys are appended to each researcher block in a
fixed order, leaving the rest of the file untouched.
"""

from __future__ import annotations

import json
import re
import sys

import common

FIELD_ORDER = ["website", "google_scholar", "orcid", "linkedin", "twitter", "bluesky", "github"]
KEY = re.compile(r"^([a-z_]+)\s*=")
ID = re.compile(r'^id\s*=\s*"([^"]+)"')


def researcher_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Line ranges of each [[organization.researchers]] block, end exclusive."""
    blocks = []
    for index, line in enumerate(lines):
        if line.strip() == "[[organization.researchers]]":
            end = index + 1
            while end < len(lines) and lines[end].strip() and not lines[end].startswith("["):
                end += 1
            blocks.append((index, end))
    return blocks


def first_id(lines: list[str]) -> str | None:
    for line in lines:
        match = ID.match(line)
        if match:
            return match.group(1)
    return None


def main() -> None:
    path = common.out_path("decisions.json")
    if not path.exists():
        sys.exit(f"{path} not found — record decisions first")
    decisions = json.loads(path.read_text())

    added = 0
    for toml_path in sorted((common.ROOT / "config/organizations").glob("*.toml")):
        lines = toml_path.read_text(encoding="utf-8").splitlines()
        org_id = first_id(lines)
        if not org_id:
            continue

        # Reverse order so earlier line numbers stay valid as we insert.
        for start, end in reversed(researcher_blocks(lines)):
            body = lines[start:end]
            researcher_id = first_id(body)
            if not researcher_id:
                continue
            wanted = decisions.get(f"{org_id}/{researcher_id}")
            if not wanted:
                continue
            present = {KEY.match(line).group(1) for line in body if KEY.match(line)}
            new = [
                f'{field} = "{wanted[field]}"'
                for field in FIELD_ORDER
                if field in wanted and field not in present
            ]
            if new:
                lines[end:end] = new
                added += len(new)

        toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"inserted {added} link lines; run `uv run pytest` and `uv run insightnet-update`")


if __name__ == "__main__":
    main()
