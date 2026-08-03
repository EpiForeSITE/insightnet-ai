import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from insightnet.config import load_profiles

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
        "view-partners",
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


def test_publications_declare_what_the_list_is_not() -> None:
    """Two things a reader would otherwise get wrong: the list is capped, and predating
    work is not InsightNet output."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    works_view = html.split('id="view-works"')[1].split("</section>")[0]

    assert "100 most recent publications per researcher" in works_view
    assert "predate InsightNet" in works_view
    assert "not a claim that the work was" in works_view


def test_the_advertised_cap_is_the_cap_collection_actually_applies() -> None:
    """The note above the list is a claim about the data, so it has to track the
    collector rather than drift into a comfortable round number."""

    cap = load_profiles(ROOT / "config/network.toml", ROOT / "config/organizations")["network"][
        "max_works_per_researcher"
    ]
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")

    assert f"{cap} most recent publications per researcher" in html


def test_the_site_credits_its_author_and_the_center_that_owns_it() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")

    assert "Site created by George G. Vega Yon with the help of AI" in html
    assert "Codex, Copilot, and Claude" in html
    assert "Copyright &copy;" in html and "ForeSITE</a>" in html


def test_the_site_carries_foresite_branding() -> None:
    """The logo ships with the site — a hotlink would break the moment the source moved,
    and the guidelines require the original artwork rather than a recreation."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    css = (ROOT / "site/assets/styles.css").read_text(encoding="utf-8")

    for asset in ("foresite-logo.png", "foresite-logo-white.png", "foresite-mark.png"):
        assert (ROOT / "site/assets" / asset).exists()
        assert asset in html

    # The three official colors, and nothing that competes with them.
    assert "--crimson: #a60f2d;" in css
    assert "--gold: #fdb921;" in css
    assert "--gray: #4e4e4e;" in css


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
        "keywords",
        "published_at",
        "url",
        "doi",
        "pmid",
        "has_abstract",
        "researcher_ids",
        "organization_ids",
    }
    assert required <= set(works[0])
    # Every record must be openable by a reader.
    assert all(work["url"] for work in works)
    # Abstracts and coauthor lists live in the detail document, not the index; keeping
    # them out is the whole point of the split.
    assert not {"abstract", "authors"} & set(works[0])


def test_works_details_document_covers_every_abstract_in_the_index() -> None:
    index_path = ROOT / "data/works.json"
    details_path = ROOT / "data/works-details.json"
    if not index_path.exists():
        pytest.skip("works.json has not been built yet")
    assert details_path.exists(), "works.json was published without its detail document"

    works = json.loads(index_path.read_text(encoding="utf-8"))["works"]
    details = json.loads(details_path.read_text(encoding="utf-8"))["details"]
    if not works:
        pytest.skip("works.json is empty")

    # Every work the index says has an abstract must actually have one to fetch, or a
    # card would sit on "Loading abstract…" forever.
    for work in works:
        if work["has_abstract"]:
            assert details.get(work["id"], {}).get("abstract"), work["id"]
    assert set(details) <= {work["id"] for work in works}


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


def test_partners_replaced_activity_as_a_dashboard_view() -> None:
    """Health partners earned a view of their own; the activity feed gave up its slot."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'data-view="partners"' in html
    assert 'data-view-panel="partners"' in html
    assert '"partners"' in javascript.split("const VIEWS =")[1].split("]")[0]

    assert 'data-view="activity"' not in html
    assert 'data-view-panel="activity"' not in html
    for removed in ("activity-filters", "activity-list", "activity-count", "latest-activity"):
        assert removed not in html
    # The view and its feed are gone, but collected activity is still searchable from the
    # expertise finder, where each record links straight out to its source.
    assert "renderActivity" not in javascript
    assert 'byId("activity-' not in javascript
    assert "results.items" in javascript

    # The overview sends readers into the new view instead of listing partners twice.
    parser = IdCollector()
    parser.feed(html)
    assert "partner-summary" in parser.ids
    assert 'data-go-to="partners"' in html


def test_the_carousel_shows_its_countdown() -> None:
    """A banner that moves on its own has to show the move coming."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    css = (ROOT / "site/assets/styles.css").read_text(encoding="utf-8")

    # The fill is driven by one animation whose duration comes from the rotation delay,
    # so the bar can never disagree with the timer that moves the slides.
    assert "@keyframes carousel-countdown" in css
    assert "var(--carousel-delay" in css
    assert '"--carousel-delay", `${CAROUSEL_DELAY}ms`' in javascript
    assert "setCarouselProgress" in javascript
    # A held or paused banner freezes the bar rather than resetting it.
    assert "animation-play-state: paused" in css
    assert 'setCarouselProgress("paused")' in javascript
    assert 'setCarouselProgress("running")' in javascript


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
