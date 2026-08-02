# InsightNet Scientific Endeavors

A lightweight, version-controlled intelligence dashboard for centers and researchers
across InsightNet. A scheduled GitHub Action collects public information once a day,
normalizes it into JSON, and commits that snapshot. The standalone HTML/CSS/JavaScript
dashboard in `site/` runs directly on GitHub Pages.

## What is included

- Center and researcher profiles managed in TOML
- A catalog of the tools and products each center has built — dashboards, software
  packages, platforms, models, and datasets — with links to each one
- A directory of the health partners behind the network — the state, local, tribal, and
  federal health agencies and the health systems each center works with
- Daily collection from public web pages, RSS/Atom, Bluesky, GitHub, and optionally
  Google Scholar through SerpAPI
- Weekly collection of papers and preprints from ORCID, Europe PMC, PubMed, arXiv,
  medRxiv/bioRxiv, and Crossref, including abstracts, keywords, and full coauthor lists
- Collected activity records with provenance and per-source health information, searchable
  from the expertise finder
- Keyword search across names, biographies, expertise, focus areas, health partners,
  publication titles and abstracts, and collected records
- A standalone, responsive GitHub Pages dashboard with no runtime server or frontend dependencies
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
provider's courtesy limits; the dashboard works without it, showing an empty
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

## Data contract

Data is split across three versioned documents so each can refresh on its own schedule
and so the browser only downloads the large publication corpus when it is needed.

`data/profiles.json` — the index the dashboard loads first:

- `network`: dashboard identity and description;
- `organizations`: configured center/researcher profiles, the center's `tools` catalog,
  and its collected overview;
- `health`: status, message, and item count for each activity source run; and
- `stats`, `generated_at`, and `schema_version`: snapshot metadata.

`data/activity.json` — `items`, the normalized activity records linked by
`organization_id`.

`data/works.json` — `works`, plus its own `health`, `stats`, and
`works_per_researcher` counts. Each work carries:

| Field | Notes |
|---|---|
| `title`, `abstract`, `keywords` | Abstract truncated to `network.abstract_max_chars` |
| `published_at`, `year` | ISO date; unknown month/day pad to the 1st |
| `url`, `doi`, `pmid`, `pmcid`, `arxiv_id` | Every record has at least one identifier or a URL |
| `authors` | Full ordered coauthor list as `{name, orcid}`, capped at 200, with `author_count` holding the true total — this is the basis for a coauthorship network |
| `type`, `venue`, `preprint_server` | `article` or `preprint`; `venue` is a journal, never a preprint server |
| `researcher_ids`, `organization_ids` | Every network member and center credited on the work |
| `sources` | Which APIs contributed to the merged record |
| `first_seen_at`, `last_seen_at` | Retention bookkeeping |

The dashboard fetches `profiles.json` and `activity.json` before the first paint and
`works.json` immediately afterward, so publications never delay the initial render while
still being searchable by the time a query is submitted.

External text should be treated as informational, not authoritative. Configure only
public sources you are permitted to process, keep profile details work-related, and
review each site's terms and robots policy before adding it.
