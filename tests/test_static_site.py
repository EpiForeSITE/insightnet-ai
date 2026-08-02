import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])


def test_static_site_has_every_dashboard_view() -> None:
    parser = IdCollector()
    parser.feed((ROOT / "site/index.html").read_text(encoding="utf-8"))

    assert {
        "view-overview",
        "view-tools",
        "view-works",
        "view-activity",
        "view-centers",
        "view-experts",
        "view-health",
    } <= parser.ids


def test_static_site_uses_local_assets_and_snapshot() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'href="./assets/styles.css"' in html
    assert 'src="./assets/app.js"' in html
    assert 'content="__SITE_BASE_URL__/og.png"' in html
    assert 'const PROFILES_URL = "./data/profiles.json"' in javascript
    assert 'const ACTIVITY_URL = "./data/activity.json"' in javascript
    assert 'const WORKS_URL = "./data/works.json"' in javascript
    assert "https://cdn" not in html.lower()
    assert "regular expression" not in html.lower()
    assert "regex" not in javascript.lower()


def test_publications_load_after_the_first_paint() -> None:
    """The works corpus is the largest payload, so it must not block initial render."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    initialize = javascript.split("async function initialize()")[1]

    assert "worksPromise = loadWorks();" in initialize
    assert "await loadWorks()" not in initialize
    # The expertise search still waits for them, so a query never answers from half the data.
    assert "await worksPromise;" in javascript


def test_static_site_identifies_itself_as_unofficial_and_links_to_insightnet() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "InsightNet Explorer" in html
    assert 'href="https://insightnet.us/"' in html
    assert "This is an unofficial InsightNet website." in html
    assert 'document.title = "InsightNet Explorer"' in javascript
    assert 'byId("network-title").textContent = "InsightNet Explorer"' in javascript


@pytest.mark.parametrize("name", ["profiles.json", "activity.json", "works.json"])
def test_static_snapshot_matches_canonical_snapshot(name: str) -> None:
    canonical = ROOT / "data" / name
    static = ROOT / "site/data" / name
    if not canonical.exists():
        pytest.skip(f"{name} has not been built yet")

    assert json.loads(static.read_text(encoding="utf-8")) == json.loads(
        canonical.read_text(encoding="utf-8")
    )


def test_profiles_snapshot_carries_center_tools() -> None:
    path = ROOT / "data/profiles.json"
    if not path.exists():
        pytest.skip("profiles.json has not been built yet")
    snapshot = json.loads(path.read_text(encoding="utf-8"))

    tools = [tool for org in snapshot["organizations"] for tool in org.get("tools", [])]
    assert tools, "expected at least one center to publish a tool"
    assert snapshot["stats"]["tools"] == len(tools)
    assert {"id", "name", "summary", "category", "status", "url"} <= set(tools[0])
    # A tool is only useful if a reader can tell what it is.
    assert all(tool["name"] and tool["summary"] for tool in tools)


def test_works_snapshot_carries_the_fields_the_dashboard_renders() -> None:
    path = ROOT / "data/works.json"
    if not path.exists():
        pytest.skip("works.json has not been built yet")
    works = json.loads(path.read_text(encoding="utf-8"))["works"]
    if not works:
        pytest.skip("works.json is empty")

    required = {
        "id",
        "title",
        "abstract",
        "keywords",
        "published_at",
        "url",
        "doi",
        "pmid",
        "authors",
        "researcher_ids",
        "organization_ids",
    }
    assert required <= set(works[0])
    # Every record must be openable by a reader.
    assert all(work["url"] for work in works)


def test_overview_features_the_centers_carousel_and_health_partners() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    parser = IdCollector()
    parser.feed(html)
    assert {
        "center-carousel",
        "carousel-dots",
        "carousel-previous",
        "carousel-next",
        "carousel-toggle",
        "partners-list",
        "partners-query",
        "partners-type",
        "partners-center",
    } <= parser.ids
    assert 'aria-roledescription="carousel"' in html
    assert "renderCarousel();" in javascript
    assert "renderPartners();" in javascript


def test_the_carousel_rotates_but_can_always_be_stopped() -> None:
    """An automatically moving banner needs an off switch and a reduced-motion opt-out."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "CAROUSEL_DELAY" in javascript
    assert "setInterval" in javascript
    # Rotation stops for an explicit pause, a hover or focus, a hidden tab, another view,
    # and for anyone who asked their system to reduce motion.
    assert "setCarouselStopped" in javascript
    assert "holdCarousel" in javascript
    assert "document.hidden" in javascript
    assert '"(prefers-reduced-motion: reduce)"' in javascript
    assert 'id="carousel-toggle"' in html
    assert 'aria-label="Pause the centers carousel"' in html


def test_health_partners_can_be_searched_and_filtered() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'id="partners-filters"' in html
    assert 'byId("partners-query")' in javascript
    assert 'byId("partners-center")' in javascript
    # Partners are part of the expertise search too, not only their own section.
    assert "partnerText(partner)" in javascript
    assert "results.partners" in javascript


def test_overview_metrics_drop_activity_records_and_source_health() -> None:
    """Those two counts confused readers, so the summary row no longer carries them."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    for removed in ("metric-items", "metric-sources", "Activity records", "Healthy sources"):
        assert removed not in html
        assert removed not in javascript


def test_profiles_snapshot_carries_center_health_partners() -> None:
    path = ROOT / "data/profiles.json"
    if not path.exists():
        pytest.skip("profiles.json has not been built yet")
    snapshot = json.loads(path.read_text(encoding="utf-8"))

    organizations = snapshot["organizations"]
    assert all(org.get("partners") for org in organizations), (
        "every center works with health partners"
    )
    partners = [partner for org in organizations for partner in org["partners"]]
    assert {"id", "name", "type", "website", "location", "acronym"} <= set(partners[0])
    assert all(partner["name"] and partner["type"] for partner in partners)
