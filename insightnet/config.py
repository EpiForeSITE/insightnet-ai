"""Load and validate the version-controlled network profiles."""

from __future__ import annotations

import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from insightnet.text import clean_text


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


ORCID_PATTERN = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.IGNORECASE)

PROFILE_URL_FIELDS = (
    "website",
    "linkedin",
    "github",
    "twitter",
    "bluesky",
    "google_scholar",
    "orcid",
    "pubmed",
    "arxiv",
    "medrxiv",
    "europepmc",
)


def orcid_id(value: str) -> str:
    """Return the bare ORCID identifier contained in a profile URL or string."""

    match = ORCID_PATTERN.search(str(value or ""))
    return match.group(1).upper() if match else ""


def _normalize_researcher(person: dict[str, Any], org_id: str) -> dict[str, Any]:
    person = deepcopy(person)
    if not person.get("full_name"):
        raise ProfileError(f"A researcher in {org_id!r} is missing full_name")
    person.setdefault("id", _slug(person["full_name"]))
    person.setdefault("role", "")
    person.setdefault("bio", "")
    person.setdefault("expertise", [])
    person.setdefault("keywords", [])
    for field in PROFILE_URL_FIELDS:
        person[field] = _valid_url(str(person.get(field, "")), f"researcher.{field}")
    person.setdefault("scholar_author_id", "")

    # Opt-in author queries. Works are only searched by name when a profile supplies an
    # explicit query, so researchers who share a name never silently collect each
    # other's papers.
    for field in ("pubmed_query", "arxiv_query"):
        person[field] = str(person.get(field, "")).strip()
    person["collect_works"] = bool(person.get("collect_works", True))

    person["orcid_id"] = orcid_id(person["orcid"])
    if person["orcid"] and not person["orcid_id"]:
        raise ProfileError(
            f"researcher.orcid in {org_id!r} is not a recognizable ORCID: {person['orcid']!r}"
        )
    if person["orcid_id"]:
        # Each of these is an exact identifier lookup rather than a name search, so it
        # always resolves to this person and is safe to derive automatically. There is no
        # ORCID-addressable medRxiv page; Europe PMC indexes medRxiv and bioRxiv
        # preprints and covers that ground precisely.
        if not person["pubmed"]:
            person["pubmed"] = (
                f"https://pubmed.ncbi.nlm.nih.gov/?term={person['orcid_id']}%5Bauid%5D"
            )
        if not person["europepmc"]:
            person["europepmc"] = f"https://europepmc.org/authors/{person['orcid_id']}"
        if not person["arxiv"]:
            person["arxiv"] = (
                f"https://arxiv.org/search/?searchtype=orcid&query={person['orcid_id']}"
            )
    return person


TOOL_CATEGORIES = {
    "dashboard",
    "package",
    "platform",
    "model",
    "dataset",
    "application",
    "other",
}
TOOL_STATUSES = {"available", "in-development", "retired"}


def _normalize_tool(tool: dict[str, Any], org_id: str) -> dict[str, Any]:
    """Validate one tool or product a center has built."""

    tool = deepcopy(tool)
    name = clean_text(str(tool.get("name", "")))
    if not name:
        raise ProfileError(f"A tool in {org_id!r} is missing name")
    tool["name"] = name
    tool["id"] = str(tool.get("id") or _slug(name))
    tool["summary"] = clean_text(str(tool.get("summary", "")))
    for field in ("url", "repository"):
        tool[field] = _valid_url(str(tool.get(field, "")), f"tool.{field}")

    category = str(tool.get("category", "other")).strip().lower()
    if category not in TOOL_CATEGORIES:
        raise ProfileError(
            f"tool.category in {org_id!r} must be one of {sorted(TOOL_CATEGORIES)}, got {category!r}"
        )
    tool["category"] = category

    status = str(tool.get("status", "available")).strip().lower()
    if status not in TOOL_STATUSES:
        raise ProfileError(
            f"tool.status in {org_id!r} must be one of {sorted(TOOL_STATUSES)}, got {status!r}"
        )
    tool["status"] = status

    tool["keywords"] = [
        clean_text(str(word)).lower() for word in tool.get("keywords", []) if clean_text(str(word))
    ]
    return tool


PARTNER_TYPES = {"state", "local", "tribal", "federal", "healthcare", "other"}


def _normalize_partner(partner: dict[str, Any], org_id: str) -> dict[str, Any]:
    """Validate one health partner a center works with.

    Partners are maintained by hand for the same reason tools are: centers name them in
    prose rather than in any machine-readable feed. `type` records what kind of health
    organization the partner is, so the dashboard can group a state agency, a county
    health department, and a health system without guessing from the name.
    """

    partner = deepcopy(partner)
    name = clean_text(str(partner.get("name", "")))
    if not name:
        raise ProfileError(f"A partner in {org_id!r} is missing name")
    partner["name"] = name
    partner["id"] = str(partner.get("id") or _slug(name))
    partner["acronym"] = clean_text(str(partner.get("acronym", "")))
    partner["summary"] = clean_text(str(partner.get("summary", "")))
    partner["location"] = clean_text(str(partner.get("location", "")))
    partner["website"] = _valid_url(str(partner.get("website", "")), "partner.website")

    partner_type = str(partner.get("type", "other")).strip().lower()
    if partner_type not in PARTNER_TYPES:
        raise ProfileError(
            f"partner.type in {org_id!r} must be one of {sorted(PARTNER_TYPES)}, "
            f"got {partner_type!r}"
        )
    partner["type"] = partner_type
    return partner


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

    org["tools"] = [_normalize_tool(item, org["id"]) for item in org.get("tools", [])]
    tool_ids = [tool["id"] for tool in org["tools"]]
    if len(tool_ids) != len(set(tool_ids)):
        raise ProfileError(f"Duplicate tool id in organization {org['id']!r}")

    org["partners"] = [_normalize_partner(item, org["id"]) for item in org.get("partners", [])]
    partner_ids = [partner["id"] for partner in org["partners"]]
    if len(partner_ids) != len(set(partner_ids)):
        raise ProfileError(f"Duplicate partner id in organization {org['id']!r}")
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
    network.setdefault("max_works_per_researcher", 100)
    network.setdefault("works_retention_years", 15)
    network.setdefault("abstract_max_chars", 1500)
    if network["website"]:
        network["website"] = _valid_url(str(network["website"]), "network.website")
    for field in (
        "retention_days",
        "max_items_per_organization",
        "max_works_per_researcher",
        "works_retention_years",
        "abstract_max_chars",
    ):
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
