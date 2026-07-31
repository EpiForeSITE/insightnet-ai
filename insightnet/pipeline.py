"""Build the versioned JSON document consumed by the dashboard."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as date_parser

from insightnet.collectors import SourceClient, collect_source
from insightnet.text import extract_keywords

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _item_id(organization_id: str, source_type: str, item: dict[str, Any]) -> str:
    identity = "|".join([organization_id, source_type, item.get("url", ""), item.get("title", "")])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _scholar_sources(organization: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for researcher in organization.get("researchers", []):
        if researcher.get("scholar_author_id"):
            sources.append(
                {
                    "type": "google_scholar",
                    "label": f"Google Scholar · {researcher['full_name']}",
                    "author_id": researcher["scholar_author_id"],
                    "researcher_id": researcher["id"],
                    "researcher_name": researcher["full_name"],
                    "keywords": researcher.get("expertise", []),
                    "max_items": 20,
                    "enabled": True,
                }
            )
    return sources


def _record_time(item: dict[str, Any], fallback: datetime) -> datetime:
    for field in ("published_at", "first_seen_at"):
        if item.get(field):
            try:
                parsed = date_parser.parse(item[field])
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except (TypeError, ValueError, OverflowError):
                pass
    return fallback


def _merge_history(
    new_items: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
    organization_ids: set[str],
    generated_at: str,
    retention_days: int,
    max_items_per_organization: int,
) -> list[dict[str, Any]]:
    previous = {
        item["id"]: deepcopy(item)
        for item in (previous_snapshot or {}).get("items", [])
        if item.get("id") and item.get("organization_id") in organization_ids
    }
    merged = dict(previous)
    for item in new_items:
        older = previous.get(item["id"], {})
        item["first_seen_at"] = older.get("first_seen_at", generated_at)
        item["last_seen_at"] = generated_at
        merged[item["id"]] = item

    generated_datetime = date_parser.parse(generated_at)
    cutoff = generated_datetime - timedelta(days=retention_days)
    grouped: dict[str, list[dict[str, Any]]] = {org_id: [] for org_id in organization_ids}
    for item in merged.values():
        if _record_time(item, generated_datetime) >= cutoff:
            grouped[item["organization_id"]].append(item)

    retained: list[dict[str, Any]] = []
    for org_items in grouped.values():
        org_items.sort(
            key=lambda item: (_record_time(item, generated_datetime), item.get("title", "")),
            reverse=True,
        )
        retained.extend(org_items[:max_items_per_organization])
    return sorted(
        retained,
        key=lambda item: (_record_time(item, generated_datetime), item.get("title", "")),
        reverse=True,
    )


def build_snapshot(
    profiles: dict[str, Any],
    client: SourceClient | None = None,
    previous_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect every enabled source while isolating individual source failures."""

    client = client or SourceClient()
    generated_at = _now()
    organizations: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []

    for configured_org in profiles.get("organizations", []):
        organization = deepcopy(configured_org)
        organization["collected_overview"] = ""
        organization["activity_count"] = 0
        organization["keywords"] = extract_keywords(
            [organization.get("summary", ""), *organization.get("focus_areas", [])],
            organization.get("keywords", []),
            limit=20,
        )
        for researcher in organization.get("researchers", []):
            researcher["keywords"] = extract_keywords(
                [researcher.get("bio", ""), *researcher.get("expertise", [])],
                researcher.get("keywords", []),
                limit=20,
            )

        sources = list(organization.get("sources", [])) + _scholar_sources(organization)
        for index, source in enumerate(sources):
            checked_at = _now()
            result = collect_source(client, source)
            source_type = source.get("type", "unknown")
            source_label = source.get("label", source_type.replace("_", " ").title())
            source_id = f"{organization['id']}:{source_type}:{index + 1}"
            if result.overview and not organization["collected_overview"]:
                organization["collected_overview"] = result.overview
            for item in result.items:
                item = deepcopy(item)
                item.update(
                    {
                        "id": _item_id(organization["id"], source_type, item),
                        "organization_id": organization["id"],
                        "source_type": source_type,
                        "source_label": source_label,
                    }
                )
                if source.get("researcher_id"):
                    item["researcher_ids"] = [source["researcher_id"]]
                else:
                    item["researcher_ids"] = []
                all_items.append(item)
            health.append(
                {
                    "source_id": source_id,
                    "organization_id": organization["id"],
                    "source_type": source_type,
                    "source_label": source_label,
                    "status": result.status,
                    "message": result.message,
                    "items_found": len(result.items),
                    "checked_at": checked_at,
                }
            )
        organizations.append(organization)

    # Merge the current pull into bounded history so older items do not disappear
    # merely because they fell outside a source's latest-N response.
    network = profiles.get("network", {})
    all_items = _merge_history(
        list({item["id"]: item for item in all_items}.values()),
        previous_snapshot,
        {organization["id"] for organization in organizations},
        generated_at,
        int(network.get("retention_days", 730)),
        int(network.get("max_items_per_organization", 1000)),
    )
    counts: dict[str, int] = {}
    for item in all_items:
        counts[item["organization_id"]] = counts.get(item["organization_id"], 0) + 1
    for organization in organizations:
        organization["activity_count"] = counts.get(organization["id"], 0)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "network": deepcopy(network),
        "stats": {
            "organizations": len(organizations),
            "researchers": sum(len(org.get("researchers", [])) for org in organizations),
            "items": len(all_items),
            "sources_ok": sum(row["status"] == "ok" for row in health),
            "sources_attention": sum(row["status"] in {"error", "blocked"} for row in health),
        },
        "organizations": organizations,
        "items": all_items,
        "health": health,
    }
