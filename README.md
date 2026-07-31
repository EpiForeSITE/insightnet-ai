# InsightNet Scientific Endeavors

A lightweight, version-controlled intelligence dashboard for centers and researchers
across InsightNet. A scheduled GitHub Action collects public information once a day,
normalizes it into JSON, and commits that snapshot. The standalone HTML/CSS/JavaScript
dashboard in `site/` runs directly on GitHub Pages.

## What is included

- Center and researcher profiles managed in TOML
- Daily collection from public web pages, RSS/Atom, Bluesky, GitHub, and optionally
  Google Scholar through SerpAPI
- A searchable activity stream with provenance and per-source health information
- Keyword search across names, biographies, expertise, focus areas, and collected records
- A standalone, responsive GitHub Pages dashboard with no runtime server or frontend dependencies
- Tests and a frozen `uv` environment

## Run it locally

Install [`uv`](https://docs.astral.sh/uv/), then:

```bash
uv sync --all-extras
uv run insightnet-update
uv run python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. The update command writes both
`data/insightnet.json` and the copy consumed by the static site at
`site/data/insightnet.json`. The website never contacts collection services itself.

## Add centers and researchers

Each center has exactly one TOML profile in `config/organizations/`; for example,
`config/organizations/accidda.toml`. Edit that center's own file to update its
description, sources, members, or expertise—no shared organization list needs to be
merged. Shared InsightNet settings are in `config/network.toml`.

Every researcher can have a name, role, biography, expertise tags, personal website,
LinkedIn, GitHub, X/Twitter, Bluesky, Google Scholar, and ORCID profile. IDs are
generated from names when omitted, but explicit, stable IDs are recommended.

Profiles are maintained by hand. `tools/profile-scaffold/` holds one-off helpers used to
bootstrap researcher links in bulk; they are not part of the daily refresh and should
not be re-run to keep profiles current.

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

## Daily GitHub workflow

`.github/workflows/refresh-data.yml` runs at 08:17 UTC every day and on manual
dispatch. It:

1. restores the exact `uv.lock` environment;
2. runs the test suite;
3. rebuilds the JSON snapshot; and
4. commits both the canonical and static-site JSON snapshots when they change.

Add `SERPAPI_API_KEY` under **Repository settings → Secrets and variables → Actions**
only if Google Scholar publication ingestion is desired. GitHub provides the other
token automatically. The workflow needs repository write permission; repositories
with protected default branches may need a bot branch and pull-request variant.

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

`data/insightnet.json` is a versioned document with:

- `network`: dashboard identity and description;
- `organizations`: configured center/researcher profiles plus collected overview;
- `items`: normalized activity records linked by `organization_id`;
- `health`: status, message, and item count for each source run; and
- `stats`, `generated_at`, and `schema_version`: snapshot metadata.

External text should be treated as informational, not authoritative. Configure only
public sources you are permitted to process, keep profile details work-related, and
review each site's terms and robots policy before adding it.
