"""Command-line entry points for scheduled data collection.

``insightnet-update`` refreshes profiles and the activity stream daily.
``insightnet-works`` refreshes scholarly works on its own, slower schedule.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from insightnet.config import load_profiles
from insightnet.pipeline import build_snapshot, split_snapshot
from insightnet.works import build_works_snapshot, merge_works_snapshot, split_works_snapshot


def write_snapshot(snapshot: dict, output: str | Path) -> None:
    """Write a complete snapshot atomically so readers never see partial JSON."""

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary_name, output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_snapshot(path: str | Path) -> dict[str, Any] | None:
    """Read a previous snapshot, treating an unreadable file as absent."""

    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Ignoring unreadable previous snapshot at {path}: {exc}")
        return None


def _publish(snapshot: dict[str, Any], output: str | Path, site_output: str | Path) -> None:
    write_snapshot(snapshot, output)
    if site_output and Path(site_output).resolve() != Path(output).resolve():
        write_snapshot(snapshot, site_output)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh InsightNet profiles and activity")
    parser.add_argument("--network-config", default="config/network.toml")
    parser.add_argument("--profiles-dir", default="config/organizations")
    parser.add_argument("--profiles-output", default="data/profiles.json")
    parser.add_argument("--activity-output", default="data/activity.json")
    parser.add_argument(
        "--site-dir",
        default="site/data",
        help="Copy the snapshots into the static GitHub Pages site (empty to disable)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Discard previously retained activity instead of merging it",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit unsuccessfully if a configured source is blocked or errors",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profiles = load_profiles(args.network_config, args.profiles_dir)
    previous = None if args.replace else read_snapshot(args.activity_output)
    snapshot = build_snapshot(profiles, previous_snapshot=previous)
    profile_document, activity_document = split_snapshot(snapshot)

    site_dir = Path(args.site_dir) if args.site_dir else None
    _publish(
        profile_document,
        args.profiles_output,
        site_dir / Path(args.profiles_output).name if site_dir else "",
    )
    _publish(
        activity_document,
        args.activity_output,
        site_dir / Path(args.activity_output).name if site_dir else "",
    )

    stats = snapshot["stats"]
    print(
        f"Wrote {args.profiles_output}: {stats['organizations']} centers, "
        f"{stats['researchers']} researchers"
    )
    print(f"Wrote {args.activity_output}: {stats['items']} activity records")
    if site_dir:
        print(f"Synchronized static site data in {site_dir}")
    if args.strict and stats["sources_attention"]:
        print(f"{stats['sources_attention']} source(s) need attention")
        return 1
    return 0


def parse_works_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the scholarly works collected for InsightNet researchers"
    )
    parser.add_argument("--network-config", default="config/network.toml")
    parser.add_argument("--profiles-dir", default="config/organizations")
    parser.add_argument("--output", default="data/works.json")
    parser.add_argument(
        "--details-output",
        default="",
        help=(
            "Where to write abstracts and coauthor lists "
            "(defaults to works-details.json beside --output)"
        ),
    )
    parser.add_argument(
        "--site-dir",
        default="site/data",
        help="Copy the works snapshot into the static site (empty to disable)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Discard previously retained works instead of merging them",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit unsuccessfully if a works source is blocked or errors",
    )
    return parser.parse_args(argv)


def works_details_path(output: str | Path, details_output: str = "") -> Path:
    """Where the abstracts and coauthor lists live for a given works index."""

    if details_output:
        return Path(details_output)
    output = Path(output)
    return output.with_name(f"{output.stem}-details{output.suffix}")


def works_main(argv: list[str] | None = None) -> int:
    args = parse_works_args(argv)
    details_output = works_details_path(args.output, args.details_output)
    profiles = load_profiles(args.network_config, args.profiles_dir)
    previous = (
        None
        if args.replace
        # The published index has no abstracts or authors, so put them back before
        # merging; otherwise every retained work would lose its text on each run.
        else merge_works_snapshot(read_snapshot(args.output), read_snapshot(details_output))
    )
    snapshot = build_works_snapshot(profiles, previous_snapshot=previous)
    index, details = split_works_snapshot(snapshot)

    site_dir = Path(args.site_dir) if args.site_dir else None
    _publish(index, args.output, site_dir / Path(args.output).name if site_dir else "")
    _publish(details, details_output, site_dir / details_output.name if site_dir else "")

    stats = snapshot["stats"]
    print(
        f"Wrote {args.output}: {stats['works']} works "
        f"({stats['preprints']} preprints, {stats['with_abstract']} with abstracts) "
        f"for {stats['researchers_with_works']} researchers"
    )
    print(f"Wrote {details_output}: abstracts and coauthor lists for {len(details['details'])} works")
    if args.strict and stats["sources_attention"]:
        print(f"{stats['sources_attention']} works source(s) need attention")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
