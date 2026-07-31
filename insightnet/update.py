"""Command-line entry point for daily data collection."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from insightnet.config import load_profiles
from insightnet.pipeline import build_snapshot


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the InsightNet dashboard data")
    parser.add_argument("--network-config", default="config/network.toml")
    parser.add_argument("--profiles-dir", default="config/organizations")
    parser.add_argument("--output", default="data/insightnet.json")
    parser.add_argument(
        "--site-output",
        default="site/data/insightnet.json",
        help="Copy the snapshot into the static GitHub Pages site (empty to disable)",
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
    previous_snapshot = None
    output = Path(args.output)
    if output.exists() and not args.replace:
        try:
            with output.open(encoding="utf-8") as handle:
                previous_snapshot = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Ignoring unreadable previous snapshot: {exc}")
    snapshot = build_snapshot(profiles, previous_snapshot=previous_snapshot)
    write_snapshot(snapshot, args.output)
    if args.site_output and Path(args.site_output).resolve() != output.resolve():
        write_snapshot(snapshot, args.site_output)
    stats = snapshot["stats"]
    print(
        f"Wrote {args.output}: {stats['organizations']} centers, "
        f"{stats['researchers']} researchers, {stats['items']} activity items"
    )
    if args.site_output:
        print(f"Synchronized static site data at {args.site_output}")
    if args.strict and stats["sources_attention"]:
        print(f"{stats['sources_attention']} source(s) need attention")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
