# InsightNet Scientific Endeavors

Academic profiles and publications for the researchers affiliated with InsightNet's
centers. A scheduled GitHub Action collects public information once a day, normalizes it
into JSON, and commits that snapshot. The standalone HTML/CSS/JavaScript website in
`site/` runs directly on GitHub Pages.

The website deliberately does not duplicate [insightnet.us](https://insightnet.us): it is
about people and the papers they wrote, and it links out for the network's centers,
partners, and programs. The collection pipeline still gathers tools, health partners, and
activity records, and they are still published under `data/` and `site/data/` — they are
simply not pages on this site.

## What is included

- Center and researcher profiles managed in TOML
- Weekly collection of papers and preprints from ORCID, Europe PMC, PubMed, arXiv,
  medRxiv/bioRxiv, and Crossref, including abstracts, keywords, and full coauthor lists
- Daily collection from public web pages, RSS/Atom, Bluesky, GitHub, and optionally
  Google Scholar through SerpAPI, with provenance and per-source health information
- An AI-assisted search that answers expert-finding questions from the publications and
  profiles in the snapshot, citing the record behind each suggestion
- A keyword search across names, biographies, expertise, and publication titles and
  abstracts, which runs entirely in the reader's browser
- A browsable, filterable publication list
- A standalone, responsive GitHub Pages site with no runtime server or frontend
  dependencies, styled to the ForeSITE brand
- Tests and a frozen `uv` environment

## Run it locally

Install [`uv`](https://docs.astral.sh/uv/), then:

```bash
uv sync --all-extras
uv run insightnet-update
uv run insightnet-works
uv run python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. Each command writes to `data/` and mirrors the result into
`site/data/` for the static site. The website never contacts collection services itself.

`insightnet-works` takes several minutes because it paces requests to stay inside each
provider's courtesy limits; the website works without it, showing an empty
**Publications** view until the first run completes.

## Add centers and researchers

Each center has exactly one TOML profile in `config/organizations/`; for example,
`config/organizations/accidda.toml`. Edit that center's own file to update its
description, sources, members, expertise, tools, or health partners—no shared
organization list needs to be merged. Shared InsightNet settings are in
`config/network.toml`.

Every researcher can have a name, role, biography, expertise tags, personal website,
LinkedIn, GitHub, X/Twitter, Bluesky, Google Scholar, ORCID, PubMed, Europe PMC, arXiv,
and medRxiv profile links. IDs are generated from names when omitted, but explicit,
stable IDs are recommended.

### Publication attribution

`orcid` is the field that drives publication collection. When it is set, the PubMed,
Europe PMC, and arXiv profile links are derived from it automatically — each is an exact
identifier lookup rather than a name search — and every works source searches by that
identifier. There is no ORCID-addressable medRxiv page, so set `medrxiv` by hand if you
want one; Europe PMC indexes medRxiv and bioRxiv preprints and covers that ground.

Researchers without an ORCID collect nothing by default. Name searches are opt-in per
person, because two researchers who share a name would otherwise silently collect each
other's papers:

```toml
[[organization.researchers]]
full_name = "Jane Q. Researcher"
# Any valid PubMed query. Narrow it with an affiliation or subject term.
pubmed_query = "Researcher JQ[au] AND (epidemiology[MeSH] OR forecasting[tiab])"
# Any valid arXiv query; a bare name is wrapped as au:"<name>".
arxiv_query = "au:\"Researcher, J\" AND cat:q-bio.PE"
# Set to false to exclude someone from publication collection entirely.
collect_works = true
```

Check the result in **Data status** before trusting a name query — every researcher and
source pair reports its own row.

Profiles are maintained by hand. `tools/profile-scaffold/` holds one-off helpers used to
bootstrap researcher links in bulk; they are not part of the daily refresh and should
not be re-run to keep profiles current.

## Add center tools and products

Each center may list what it has built under `[[organization.tools]]`:

```toml
[[organization.tools]]
name = "RespiLens"
summary = "Flexible dashboard for exploring respiratory disease trends."
url = "https://www.respilens.com/"
repository = "https://github.com/ACCIDDA/..."   # optional
category = "dashboard"    # dashboard | package | platform | model | dataset | application | other
status = "available"      # available | in-development | retired
keywords = ["respiratory disease", "forecasting"]
```

Unlike publications, tools are transcribed by hand from each center's public pages —
centers describe them in prose, not in any machine-readable feed, so there is nothing
reliable to collect automatically. Record only what a center actually names as a
deliverable; a stated goal is not a tool. Mark anything announced but not yet released as
`status = "in-development"` and the dashboard labels it as such.

Validate a change and rebuild the snapshot with:

```bash
uv run pytest
uv run insightnet-update
```

Individual source failures are recorded in the JSON and shown in **Data status**;
they do not discard successful updates from other sources. Use
`uv run insightnet-update --strict` in a separate monitoring job if any blocked/error
source should fail the run.

Each refresh merges newly collected records into the previous snapshot. By default,
records are retained for 730 days, capped at 1,000 per center; change
`network.retention_days` or `network.max_items_per_organization` in
`config/network.toml` as needed. Use `uv run insightnet-update --replace` for a clean
rebuild.

Publications merge the same way, bounded by `network.max_works_per_researcher` (100),
`network.works_retention_years` (15), and `network.abstract_max_chars` (1500). Because a
work is capped per researcher rather than globally, a prolific author never crowds out a
smaller center. Use `uv run insightnet-works --replace` to rebuild from scratch.

The **Publications** view states both caveats a reader needs before drawing a conclusion
from that list: it holds at most the 100 most recent papers per researcher, so some work
is missing; and many of the papers predate InsightNet, so listing one is not a claim that
InsightNet funded or supported it. `tests/test_static_site.py` ties the number in that
note to `max_works_per_researcher`, so raising the cap fails the suite until the note
agrees with it again.

## Source support

| Source | Configuration | Credential | Behavior |
|---|---|---:|---|
| Website | `type = "website"`, `url` | No | Reads description/body and semantic `<article>` elements; honors `robots.txt` |
| RSS/Atom | `type = "rss"`, `url` | No | Preferred, reliable news/publication ingestion |
| Bluesky | `type = "bluesky"`, `handle` | No | Uses Bluesky's public AppView API |
| GitHub | `type = "github"`, `organization` | Optional | Reads recently pushed public repositories; the Action supplies `GITHUB_TOKEN` |
| Google Scholar | Researcher `scholar_author_id` | `SERPAPI_API_KEY` | Reads recent author publications through SerpAPI; profile links work without the key |
| LinkedIn / X | Profile links | — | Shown in profiles; ingestion is skipped until approved API access or a permitted RSS bridge is configured |

Google Scholar has no official general-purpose public API, and LinkedIn/X restrict
automated access. The first version avoids brittle scraping or bypassing access
controls. If the project later gains approved API access, add a collector behind the
same normalized source contract.

## Publication sources

Each source runs per researcher and reports its own health row. Every one is a public,
documented API needing no credentials.

| Source | Driven by | Contributes |
|---|---|---|
| Europe PMC | `orcid` | Abstracts, keywords, MeSH terms, coauthors, DOI/PMID/PMCID; indexes medRxiv and bioRxiv preprints |
| ORCID | `orcid` | The author's own claimed record: titles, dates, and identifiers, including work no index covers |
| PubMed | `orcid`, or `pubmed_query` | Abstracts, MeSH terms, coauthors with ORCIDs; honors `NCBI_API_KEY` |
| arXiv | `arxiv_query` | Preprint abstracts, subject categories, and author lists |
| Crossref | Any DOI | Coauthors and metadata for work outside the life sciences, which Europe PMC and PubMed do not index |
| medRxiv/bioRxiv | Any `10.1101/…` DOI | Preprint abstracts and author lists as a fallback |

Records are merged across sources by DOI, then PubMed ID, then arXiv ID, then normalized
title, so one paper appears once with the union of what every source knew about it. A
preprint that was later published is reported as the published article while keeping the
preprint server for provenance.

Set `INSIGHTNET_CONTACT_EMAIL` to reach Crossref's polite pool, and add an optional
`NCBI_API_KEY` to raise the PubMed rate limit from 3 to 10 requests per second.

## Scheduled GitHub workflows

`.github/workflows/refresh-data.yml` runs at 08:17 UTC every day and on manual
dispatch. It:

1. restores the exact `uv.lock` environment;
2. runs the test suite;
3. rebuilds `profiles.json` and `activity.json`; and
4. commits both the canonical and static-site copies when they change.

`.github/workflows/refresh-works.yml` runs at 06:23 UTC on Sundays and on manual
dispatch, rebuilding `works.json`. Publication metadata changes slowly and collection
touches five external APIs per researcher, so it deliberately runs weekly rather than
inside the daily job. Manual dispatch accepts a `replace` input for a clean rebuild.

Add `SERPAPI_API_KEY` under **Repository settings → Secrets and variables → Actions**
only if Google Scholar publication ingestion is desired, and `NCBI_API_KEY` to speed up
PubMed collection. GitHub provides the other token automatically. Both workflows need
repository write permission; repositories with protected default branches may need a bot
branch and pull-request variant.

## Deploy on GitHub Pages

The repository includes `.github/workflows/deploy-pages.yml`. After pushing to GitHub:

1. Open **Settings → Pages** in the repository.
2. Under **Build and deployment → Source**, select **GitHub Actions**.
3. Run **Deploy GitHub Pages** once from the Actions tab, or push to `main`.

GitHub will publish the `site/` directory at
`https://<owner>.github.io/<repository>/`. Every daily data refresh updates both JSON
copies, commits them, and triggers another Pages deployment automatically. All
filtering and keyword search run locally in the visitor's browser.

The deployment step rewrites two placeholders in `site/index.html` — `__SITE_BASE_URL__`
and `__APP_VERSION__` — and fails if either survives. Nothing else is built, minified, or
transformed.

## Versioning

The version lives in exactly one place:

```python
# insightnet/__init__.py
__version__ = "1.0.0"
```

`pyproject.toml` reads it through `[tool.setuptools.dynamic]`, the Pages deployment
stamps it into the site footer, and each release is tagged `v<version>`. Never write a
version number anywhere else — the footer carries a `__APP_VERSION__` placeholder, not a
literal, and `tests/test_static_site.py` fails if a hardcoded one appears.

The footer links to
[the latest release](https://github.com/EpiForeSITE/insightnet-explorer/releases/latest),
which is where features and fixes are described. A local checkout served with
`python -m http.server` shows **dev build** instead of a number, because the placeholder
is only substituted at deploy time — that is expected, not a bug.

### What to bump

The scheme is `major.minor.patch`.

| Part | Bump it when | Examples |
|---|---|---|
| **major** | A change breaks something people depend on, or the site's purpose or shape changes | Removing a view or a published JSON field; renaming a data file; changing what a URL means |
| **minor** | Something new arrives and everything that worked still works | A new view, a new filter, a new collection source, a new field added to a snapshot |
| **patch** | A defect is corrected, or something is tidied with no change in behavior | A search that returned wrong results; a broken link; wording, styling, comments, refactors, and test-only changes |

Bump only the highest part that applies, and reset the parts to its right: a new feature
on `1.4.2` gives `1.5.0`, not `1.5.2`. Bump once per change, not once per commit within
it.

### Cutting a release

1. Bump `__version__` in `insightnet/__init__.py`.
2. Run `uv lock` so the lock file follows, and `uv run pytest`.
3. Merge to `main` — Pages redeploys and the footer shows the new number.
4. Tag and publish the release, so the footer's link lands on the right notes:

```bash
gh release create "v$(python -c 'import insightnet; print(insightnet.__version__)')" --generate-notes
```

## Branding and attribution

The site follows the ForeSITE logo guidelines. Three official colors carry the whole
design, and `site/assets/styles.css` defines them once at the top:

| Color | Hex | Pantone | Used for |
|---|---|---|---|
| Crimson | `#a60f2d` | 201 C | Links, section kickers, accents, the footer rule |
| Gold | `#fdb921` | 1235 C | Secondary accent, "current"/"ok" status, callout rule |
| Dark gray | `#4e4e4e` | 7540 C | Body copy and the footer band |

Nothing else in the stylesheet may introduce a competing hue; everything else is a tint
or shade of those three. Note that the guideline PDF prints a hex value for dark gray
(`9A5107`) that contradicts its own RGB, CMYK, and Pantone values for that swatch — the
RGB build (78, 78, 78) and PMS 7540 C agree with each other and with the wordmark in the
artwork, so `#4e4e4e` is what the site uses.

The logo is shipped, never recreated: `site/assets/` holds proportionally scaled copies
of the original primary and reverse artwork, plus a square version used as the favicon.
The guidelines' clear-space rule is reserved in CSS as padding around each placement, and
the reverse logo appears only on the flat dark-gray footer, which is the quiet,
high-contrast field it requires.

The logo is set in Proxima Nova Semibold. That face is licensed and cannot ship with a
dependency-free static site, so the CSS asks for it first and falls back to the closest
widely installed geometric humanist sans faces.

The site is credited in the footer to George G. Vega Yon, written with AI assistance
(Codex, Copilot, and Claude), copyright ForeSITE.

## Data contract

Data is split across four versioned documents so each can refresh on its own schedule
and so the browser only downloads the large publication corpus when it is needed.

`data/profiles.json` — the index the dashboard loads first:

- `network`: dashboard identity and description;
- `organizations`: configured center/researcher profiles, the center's `tools` catalog,
  and its collected overview;
- `health`: status, message, and item count for each activity source run; and
- `stats`, `generated_at`, and `schema_version`: snapshot metadata.

`data/activity.json` — `items`, the normalized activity records linked by
`organization_id`.

`data/works.json` — the publication index: `works`, plus its own `health`, `stats`, and
`works_per_researcher` counts. Each work carries:

| Field | Notes |
|---|---|
| `title`, `keywords` | |
| `published_at`, `year` | ISO date; unknown month/day pad to the 1st |
| `url`, `doi`, `pmid`, `pmcid`, `arxiv_id` | Every record has at least one identifier or a URL |
| `author_count` | The true number of coauthors, so a card can be rendered before the names arrive |
| `has_abstract` | Whether `works-details.json` holds an abstract for this record |
| `type`, `venue`, `preprint_server` | `article` or `preprint`; `venue` is a journal, never a preprint server |
| `researcher_ids`, `organization_ids` | Every network member and center credited on the work |
| `sources` | Which APIs contributed to the merged record |
| `first_seen_at`, `last_seen_at` | Retention bookkeeping |

`data/works-details.json` — `details`, keyed by work `id`:

| Field | Notes |
|---|---|
| `abstract` | Truncated to `network.abstract_max_chars` |
| `authors` | Full ordered coauthor list as `{name, orcid}`, capped at 200 — this is the basis for a coauthorship network |

Abstracts and coauthor lists are roughly three quarters of the corpus by size, and they
matter only once a reader is looking at publications, so they are published separately.
The website fetches `profiles.json` before the first paint, `works.json` immediately
afterward, and `works-details.json` once the browser is idle or as soon as the reader
opens **Publications** or the home page's searches — whichever comes first. Both searches
wait for it, so a query never returns a partial answer.

Splitting by field rather than by center is deliberate: a work co-authored across centers
carries several `organization_ids`, so per-center files would duplicate the heaviest
records and a network-wide search would have to fetch all of them anyway.

`insightnet-works` writes both documents and reads both back on the next run, so retained
abstracts survive the merge. `split_works_snapshot` and `merge_works_snapshot` in
`insightnet/works.py` are exact inverses and are tested as such.

External text should be treated as informational, not authoritative. Configure only
public sources you are permitted to process, keep profile details work-related, and
review each site's terms and robots policy before adding it.
