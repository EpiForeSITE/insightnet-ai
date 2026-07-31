# Profile scaffolding tools

**These scripts are for bootstrapping only. They are not part of the daily refresh,
and they must never be wired into CI.**

`config/organizations/*.toml` is the source of truth for researcher profiles, and it is
meant to be edited by hand. These scripts exist because the first pass over ~150
researchers was too large to do entirely by hand: they gather *candidate* identifiers
from public APIs so a person can adjudicate them.

Re-running them wholesale is a bad idea. Matching a name to a profile is a judgment
call, and a rerun would happily replace a hand-verified link with a lower-confidence
guess. When one researcher joins or changes their handle, edit that center's TOML file
directly.

## Why a human stays in the loop

Nothing here decides anything. Each script prints candidates plus the evidence behind
them — affiliation history, employment records, publication titles, profile bios — and
a person decides what is certain enough to keep. Common names are the hazard: an
OpenAlex cluster for "Claire Smith" merges several people, and an ORCID record with no
employments and no works proves nothing about who owns it.

The rule used for the initial pass: accept a link only when the evidence ties the
profile to *this* researcher's institution or research area. A name match on its own
is not enough.

## Scripts

Run from the repository root. Output goes to `.scaffold/` (git-ignored) unless
`INSIGHTNET_SCAFFOLD_DIR` says otherwise.

| Script | What it does |
| --- | --- |
| `harvest.py` | For every researcher: OpenAlex author search (ORCID + affiliation history), the ORCID record behind each hit, and a Bluesky actor search. Writes `harvest.json`. |
| `orcid_search.py` | Searches the ORCID registry by name and keeps records whose affiliations match the center. Better than OpenAlex for people with few or no indexed publications. |
| `inspect_orcid.py` | For names with only a handful of ORCID records, prints employments, education, work titles, and self-reported URLs so a rare name can be confirmed or rejected. |
| `review.py` | Compact per-researcher view of the harvest: best ORCID candidates and name-matching Bluesky accounts, with the matching evidence. |
| `record.py` | Merges adjudicated links into `decisions.json`, normalizing bare ORCID iDs, Scholar user ids, and handles into full URLs. |
| `apply.py` | Writes `decisions.json` into the TOML profiles. Never overwrites a value that is already there. |

Google Scholar has no usable API and blocks scraping, so Scholar profiles were found by
web search and confirmed against the affiliation shown on the profile. There is no
script for that step.

## Rate limits

OpenAlex meters requests against a daily budget; running several copies in parallel
exhausts it, after which the API returns empty result sets rather than an error you
would notice. Run `harvest.py` once, sequentially. The ORCID and Bluesky public APIs
were not a problem at this scale.
