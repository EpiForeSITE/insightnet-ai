import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import insightnet
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


RETIRED_VIEWS = ("ask", "tools", "partners", "centers", "experts")


def test_static_site_has_every_dashboard_view() -> None:
    parser = IdCollector()
    parser.feed((ROOT / "site/index.html").read_text(encoding="utf-8"))

    assert {"view-overview", "view-works", "view-health"} <= parser.ids


def test_static_site_uses_local_assets_and_snapshot() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'href="./assets/styles.css"' in html
    assert 'src="./assets/app.js"' in html
    assert 'content="__SITE_BASE_URL__/og.png"' in html
    assert 'const PROFILES_URL = "./data/profiles.json"' in javascript
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

    assert 'href="https://ggvy.cl"' in html
    assert "George G. Vega Yon" in html
    assert 'href="https://github.com/EpiForeSITE/insightnet-explorer"' in html
    assert "source code on GitHub" in html
    assert "Codex, Copilot, and Claude" in html
    assert "Copyright &copy;" in html and "ForeSITE</a>" in html


def test_static_site_loads_google_analytics() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")

    assert 'src="https://www.googletagmanager.com/gtag/js?id=G-Z3SR14RDZF"' in html
    assert 'gtag("config", "G-Z3SR14RDZF");' in html


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


def test_the_top_menu_is_publications_the_official_centers_page_and_data_status() -> None:
    """The network's own site already lists its centers and their people, so this menu
    carries what only this site has and links out for the rest."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    nav = html.split('<nav aria-label="Primary navigation">')[1].split("</nav>")[0]

    assert 'data-view="works"' in nav and "Publications" in nav
    assert 'data-view="health"' in nav and "Data status" in nav
    assert 'href="https://insightnet.us/network/#centers"' in nav
    # Nothing else, and in particular not a second route to the home page.
    for removed in ("overview", *RETIRED_VIEWS):
        assert f'data-view="{removed}"' not in nav


def test_the_retired_views_left_no_markup_or_dead_code_behind() -> None:
    """Tools, health partners, center profiles and the activity feed moved off the site.
    Their data is still published; their pages, renderers and styles are not."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    css = (ROOT / "site/assets/styles.css").read_text(encoding="utf-8")

    views = javascript.split("const VIEWS =")[1].split("]")[0]
    for view in RETIRED_VIEWS:
        assert f'id="view-{view}"' not in html
        assert f'data-view-panel="{view}"' not in html
        assert f'"{view}"' not in views

    for renderer in (
        "renderCarousel",
        "renderPartners",
        "renderTools",
        "renderCenter",
        "activityCard",
        "allPartners",
        "allTools",
        "CAROUSEL_DELAY",
    ):
        assert renderer not in javascript

    for selector in (".carousel", ".partner-card", ".tools-grid", ".metrics {", ".metric-value"):
        assert selector not in css


def test_the_home_page_says_what_it_holds_instead_of_a_wall_of_counters() -> None:
    """Five oversized counters were the loudest thing on the page. One quiet sentence
    carries the two numbers that matter and hands everything else to insightnet.us."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    for removed in (
        'class="metrics"',
        "metric-centers",
        "metric-researchers",
        "metric-partners",
        "metric-tools",
        "metric-works",
    ):
        assert removed not in html
        assert removed not in javascript

    summary = javascript.split("function renderSummary()")[1].split("\n  }")[0]
    assert "This site contains academic profiles for the" in summary
    assert "affiliated members" in summary
    assert "The latest version includes" in summary
    assert "publications" in summary
    assert "insightnet.us" in summary
    # The counts are read off the snapshot, so the sentence cannot drift from the data.
    assert "snapshot?.stats" in summary
    assert "works.stats?.works" in summary
    # The publication count arrives with the second fetch, so the line is written again
    # once it lands rather than being held back until then.
    assert "renderSummary();" in javascript.split("function loadWorks()")[1]


def test_the_keyword_search_answers_with_researchers_and_publications() -> None:
    """People and their papers are the whole site now, so the search returns those two
    and does not rebuild the directories the network's own site owns."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    search = javascript.split("function searchExperts(")[1].split("function renderExpertResults")[0]
    renderer = javascript.split("function renderExpertResults(")[1].split(
        "async function runKeywordSearch"
    )[0]

    assert "researchers.push(" in search
    assert "matchedWorks.push(" in search
    # A center's name and focus areas still count toward its members' scores, which is how
    # a center-shaped query reaches people.
    assert "org.focus_areas," in search
    for gone in ("organizations.push(", "tools.push(", "partners.push(", "items.push("):
        assert gone not in search

    assert "results.researchers" in renderer
    assert "results.works" in renderer
    for gone in ("results.tools", "results.partners", "results.organizations", "results.items"):
        assert gone not in renderer


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


def test_the_assistant_appears_on_the_home_page_and_nowhere_else() -> None:
    """The ask bar used to sit above the router, so it followed a reader onto every view.
    It now lives inside the home panel, which is the only page it belongs on."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    home = html.split('id="view-overview"')[1].split('id="view-works"')[0]
    assert 'class="hero"' in home
    assert 'id="ask-form"' in home
    assert 'id="ask-query"' in home
    assert 'id="ask-answer"' in home
    # One ask box in the whole document: the duplicate that lived in the old Ask view is
    # gone rather than merely hidden.
    assert html.count('id="ask-query"') == 1
    assert 'id="ask-query-view"' not in html
    assert 'showView("overview")' in javascript.split("async function askQuestion")[1]


def test_the_keyword_search_shares_the_home_page_but_not_the_assistant() -> None:
    """The two searches sit one above the other; only the top one talks to a model."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    home = html.split('id="view-overview"')[1].split('id="view-works"')[0]

    assert 'id="expert-form"' in home
    assert 'id="expert-query"' in home
    assert 'id="expert-results"' in home
    # The keyword section says plainly that it is the one that does not use a model.
    assert "no AI involved" in home
    assert home.index('id="ask-form"') < home.index('id="expert-form"')


def test_the_assistant_degrades_to_the_keyword_search_below_it() -> None:
    """Every failure path ends in results rather than a dead end."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    fallback = javascript.split("async function askFallback")[1].split("\n  }")[0]

    assert "runKeywordSearch(" in fallback
    # The keyword box is filled in with the question, so the fallback shows its work
    # instead of producing results from nowhere.
    assert 'byId("expert-query").value = query' in fallback
    # Rate limiting, budget exhaustion, a network failure and an unconfigured endpoint
    # all have to reach it, or the page can strand a visitor.
    for trigger in (
        "rate_limited",
        "budget_exhausted",
        "not configured yet",
        "could not be reached",
    ):
        assert trigger in javascript


def test_a_question_too_long_for_the_keyword_index_reports_instead_of_throwing() -> None:
    """The ask bar accepts 300 characters and the keyword index reads 120, so a long
    question arriving by fallback has to land on a message rather than an exception."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    runner = javascript.split("async function runKeywordSearch")[1].split("\n  }")[0]

    assert "try {" in runner and "catch (error)" in runner
    assert "errorBox.textContent = error.message" in runner
    assert "errorBox.hidden = false" in runner


def test_the_answer_stream_is_announced_without_spamming_the_screen_reader() -> None:
    """A live region that mutates every frame is unusable; the finished text is announced once."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    answer = html.split('id="ask-answer"')[1].split(">")[0]
    assert 'aria-live="off"' in answer
    assert 'id="ask-status" class="result-count" role="status" aria-live="polite"' in html
    assert 'id="ask-answer-sr"' in html
    assert 'byId("ask-answer-sr").textContent' in javascript


def test_the_ask_endpoint_is_public_and_carries_no_secret() -> None:
    """The endpoint is a public URL, not a credential, and never a build-time placeholder."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    value = javascript.split("const ASK_URL =")[1].split(";")[0].strip().strip('"')

    assert value == "" or value.startswith("https://")
    assert "__SITE_BASE_URL__" not in value
    assert "key" not in value.lower()


def test_only_offered_citations_can_become_links() -> None:
    """Markers are substituted literally, so an invented one cannot be turned into a link."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    renderer = javascript.split("function renderAskAnswer")[1].split("\n  }")[0]

    assert "escapeHtml(text)" in renderer
    # Numbered by order of appearance, so footnotes read 1, 2, 3 rather than by the
    # position of the document in the far longer list retrieval offered the model.
    assert "citedInOrder" in renderer
    assert "replaceAll(`[[${entry.id}]]`" in renderer
    assert "ASK_MARKER" in renderer  # anything left over is stripped, not rendered


def test_the_ask_view_discloses_where_the_question_goes() -> None:
    """The keyword view promises the query stays local; that must not silently become false."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    assert "Your query stays in this browser." in html
    assert "Your question is sent to Google Cloud to be answered." in html


def test_a_failed_stream_leaves_no_half_written_answer() -> None:
    """An upstream quota can be exhausted after some prose has already painted.

    Half a sentence sitting above "showing keyword matches instead" reads like a broken
    page, so the partial answer is cleared before the fallback renders.
    """

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    branch = javascript.split("if (refusal || !answer.trim())")[1].split("askFallback(")[0]

    assert 'byId("ask-answer").innerHTML = ""' in branch
    assert 'byId("ask-answer-sr").textContent = ""' in branch
    assert 'byId("ask-citations").innerHTML = ""' in branch


def test_a_deep_link_to_a_view_that_wants_abstracts_does_not_crash() -> None:
    """Opening #ask directly must not run routing before the works fetch exists.

    `worksPromise` starts as null and `loadWorkDetails` chains onto it, so restoring a
    view from the hash before the fetch was started threw inside initialize() and left
    the page with no publications at all. Sharing a link to #ask is the normal case, so
    both the ordering and the guard are pinned here.
    """

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    initialize = javascript.split("async function initialize()")[1]

    assert initialize.index("worksPromise = loadWorks();") < initialize.index(
        "showView(window.location.hash"
    )
    loader = javascript.split("function loadWorkDetails()")[1].split("\n  }")[0]
    assert "if (!worksPromise) return Promise.resolve();" in loader


# ----------------------------------------------------------------------------------
# Versioning
# ----------------------------------------------------------------------------------


def test_the_version_has_exactly_one_source_of_truth() -> None:
    """`insightnet.__version__` is the only place a version number is written down.

    pyproject reads it, the deployment stamps it into the footer, and releases are tagged
    from it. A literal typed anywhere else is a number that will silently go stale.
    """

    assert re.fullmatch(r"\d+\.\d+\.\d+", insightnet.__version__), insightnet.__version__

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = { attr = "insightnet.__version__" }' in pyproject
    # A static `version = "x.y.z"` under [project] would shadow the dynamic one.
    assert not re.search(r'^version = "\d', pyproject, re.MULTILINE)

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    assert insightnet.__version__ not in html
    assert insightnet.__version__ not in javascript


def test_the_footer_shows_the_version_and_links_to_the_latest_release() -> None:
    """A reader who wants to know what changed needs one click from the page they are on."""

    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    footer = html.split('<footer class="site-footer">')[1]

    assert "Version" in footer
    assert 'id="app-version"' in footer
    # The placeholder, not a number: the deployment fills it from the package metadata.
    assert "v__APP_VERSION__" in footer
    assert 'href="https://github.com/EpiForeSITE/insightnet-explorer/releases/latest"' in footer
    assert 'rel="noopener noreferrer"' in footer


def test_the_deployment_substitutes_the_version_and_refuses_to_ship_a_placeholder() -> None:
    """The footer is only honest if the build always fills it in, so the workflow reads
    the version from the package and fails rather than publishing the raw placeholder."""

    workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")

    assert "import insightnet; print(insightnet.__version__)" in workflow
    assert "s|__APP_VERSION__|${APP_VERSION}|g" in workflow
    assert 'grep -q "__APP_VERSION__\\|__SITE_BASE_URL__"' in workflow
    assert "exit 1" in workflow
    # A bump touches no file under site/, so it needs its own trigger to reach Pages.
    assert '- "insightnet/__init__.py"' in workflow


def test_an_unsubstituted_version_reads_as_a_dev_build() -> None:
    """Serving the checkout directly leaves the placeholder in place; showing it raw
    would look broken, so the page says what it actually is."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    renderer = javascript.split("function renderVersion()")[1].split("\n  }")[0]

    assert '"dev build"' in renderer
    assert r"^v\d+\.\d+\.\d+$" in renderer
    # It describes the code rather than the data, so it must not wait on the snapshot.
    initialize = javascript.split("async function initialize()")[1]
    assert initialize.index("renderVersion();") < initialize.index("try {")


def test_the_versioning_rules_reach_both_humans_and_agents() -> None:
    """The scheme only holds if every contributor meets it, and agents read AGENTS.md."""

    for path in ("README.md", "AGENTS.md"):
        document = (ROOT / path).read_text(encoding="utf-8")
        assert "major.minor.patch" in document, path
        assert "insightnet/__init__.py" in document, path
        for part in ("**major**", "**minor**", "**patch**"):
            assert part in document, f"{path} does not say when to bump {part}"

    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Every change bumps the version." in agents
    assert "uv lock" in agents


def test_the_assistant_answers_with_a_list_of_people_not_a_paragraph() -> None:
    """ "Who can help with X" has a set of people as its answer, and ten names buried in
    prose cannot be scanned or compared. A lead sentence plus one bullet each can.
    """

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    css = (ROOT / "site/assets/styles.css").read_text(encoding="utf-8")
    renderer = javascript.split("function answerHtml(")[1].split("\n  }")[0]

    assert "answerHtml(html)" in javascript
    assert "ask-people" in renderer
    assert "<li>" in renderer and "<p>" in renderer
    # It runs over text that is already escaped and already carries its citation links,
    # so the only HTML it can introduce is the list scaffolding written right here.
    assert "escapeHtml" not in renderer
    assert ".ask-people" in css


def test_a_question_that_matches_nothing_says_so_in_its_own_words() -> None:
    """Finding nothing is a normal outcome, not a failure, and it used to borrow the
    wording used when the service is unreachable."""

    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "Couldn't find any researchers or publications relevant to your question." in javascript
    # Retrieval that matched nothing answers with JSON rather than a stream. Reading it
    # as SSE yields no events by accident, which makes a real no-match look identical to
    # a stream that died halfway, so it is recognised by content type.
    assert 'includes("text/event-stream")' in javascript
    # A model refusal and a broken stream are different things and read differently.
    assert 'refusal = "no_match"' in javascript
    assert 'refusal = "error"' in javascript
