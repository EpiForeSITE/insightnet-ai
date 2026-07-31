import json
from html.parser import HTMLParser
from pathlib import Path

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
    assert 'const DATA_URL = "./data/insightnet.json"' in javascript
    assert "https://cdn" not in html.lower()
    assert "regular expression" not in html.lower()
    assert "regex" not in javascript.lower()


def test_static_site_identifies_itself_as_unofficial_and_links_to_insightnet() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "InsightNet Explorer" in html
    assert 'href="https://insightnet.us/"' in html
    assert "This is an unofficial InsightNet website." in html
    assert 'document.title = "InsightNet Explorer"' in javascript
    assert 'byId("network-title").textContent = "InsightNet Explorer"' in javascript


def test_static_snapshot_matches_canonical_snapshot() -> None:
    canonical = json.loads((ROOT / "data/insightnet.json").read_text(encoding="utf-8"))
    static = json.loads((ROOT / "site/data/insightnet.json").read_text(encoding="utf-8"))

    assert static == canonical
