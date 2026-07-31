"""Load and validate the version-controlled network profiles."""

from __future__ import annotations

import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class ProfileError(ValueError):
    """Raised when an organization profile is incomplete or inconsistent."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"Invalid TOML in {path}: {exc}") from exc


def _valid_url(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProfileError(f"{field} must be an http(s) URL, got {value!r}")
    return value


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _normalize_researcher(person: dict[str, Any], org_id: str) -> dict[str, Any]:
    person = deepcopy(person)
    if not person.get("full_name"):
        raise ProfileError(f"A researcher in {org_id!r} is missing full_name")
    person.setdefault("id", _slug(person["full_name"]))
    person.setdefault("role", "")
    person.setdefault("bio", "")
    person.setdefault("expertise", [])
    person.setdefault("keywords", [])
    for field in (
        "website",
        "linkedin",
        "github",
        "twitter",
        "bluesky",
        "google_scholar",
        "orcid",
    ):
        person[field] = _valid_url(str(person.get(field, "")), f"researcher.{field}")
    person.setdefault("scholar_author_id", "")
    return person


def _normalize_source(source: dict[str, Any], org_id: str) -> dict[str, Any]:
    source = deepcopy(source)
    source_type = str(source.get("type", "")).strip().lower()
    if not source_type:
        raise ProfileError(f"A source in {org_id!r} is missing type")
    source["type"] = source_type
    source.setdefault("label", source_type.replace("_", " ").title())
    source.setdefault("enabled", True)
    source.setdefault("max_items", 20)
    if "url" in source:
        source["url"] = _valid_url(str(source["url"]), f"source.{source_type}.url")
    return source


def _normalize_organization(org: dict[str, Any]) -> dict[str, Any]:
    org = deepcopy(org)
    if not org.get("name"):
        raise ProfileError("Every organization must have a name")
    org.setdefault("id", _slug(org["name"]))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", org["id"]):
        raise ProfileError(f"Invalid organization id {org['id']!r}")
    org.setdefault("acronym", "")
    org.setdefault("summary", "")
    org.setdefault("location", "")
    org.setdefault("focus_areas", [])
    org.setdefault("keywords", [])
    org.setdefault("enabled", True)
    org["website"] = _valid_url(str(org.get("website", "")), "organization.website")
    org["logo_url"] = _valid_url(str(org.get("logo_url", "")), "organization.logo_url")

    social = dict(org.get("social", {}))
    for field in ("linkedin", "github", "twitter", "bluesky"):
        social[field] = _valid_url(str(social.get(field, "")), f"social.{field}")
    org["social"] = social
    org["sources"] = [_normalize_source(item, org["id"]) for item in org.get("sources", [])]
    org["researchers"] = [
        _normalize_researcher(item, org["id"]) for item in org.get("researchers", [])
    ]
    researcher_ids = [person["id"] for person in org["researchers"]]
    if len(researcher_ids) != len(set(researcher_ids)):
        raise ProfileError(f"Duplicate researcher id in organization {org['id']!r}")
    return org


def load_profiles(
    network_path: str | Path = "config/network.toml",
    profiles_dir: str | Path = "config/organizations",
) -> dict[str, Any]:
    """Load the shared network settings and one TOML profile per organization."""

    network_path = Path(network_path)
    profiles_dir = Path(profiles_dir)
    document: dict[str, Any] = {"network": {}, "organizations": []}

    if network_path.exists():
        network_document = _read_toml(network_path)
        if set(network_document) - {"network"}:
            raise ProfileError(
                f"{network_path} may contain only [network]; "
                "put each organization in config/organizations/<id>.toml"
            )
        document["network"].update(network_document.get("network", {}))

    if profiles_dir.exists():
        for path in sorted(profiles_dir.glob("*.toml")):
            fragment = _read_toml(path)
            if set(fragment) != {"organization"} or not isinstance(fragment["organization"], dict):
                raise ProfileError(f"{path} must contain exactly one [organization] profile table")
            document["organizations"].append(fragment["organization"])

    network = document["network"]
    network.setdefault("name", "InsightNet")
    network.setdefault("description", "Scientific activity across the network")
    network.setdefault("website", "")
    network.setdefault("retention_days", 730)
    network.setdefault("max_items_per_organization", 1000)
    if network["website"]:
        network["website"] = _valid_url(str(network["website"]), "network.website")
    for field in ("retention_days", "max_items_per_organization"):
        try:
            network[field] = int(network[field])
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"network.{field} must be an integer") from exc
        if network[field] < 1:
            raise ProfileError(f"network.{field} must be at least 1")

    organizations = [_normalize_organization(item) for item in document["organizations"]]
    organizations = [item for item in organizations if item["enabled"]]
    ids = [item["id"] for item in organizations]
    if len(ids) != len(set(ids)):
        raise ProfileError("Organization ids must be unique across all profile files")
    document["organizations"] = organizations
    return document
