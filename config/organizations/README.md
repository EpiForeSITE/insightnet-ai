# Organization profiles

Each `*.toml` file in this directory describes exactly one InsightNet organization.
To update a center, edit only its matching file—there is no shared organization list to
merge or coordinate.

Every profile starts with `[organization]` and may include:

- `[organization.social]` for organization links;
- `[[organization.sources]]` for public collection sources;
- `[[organization.researchers]]` for member profiles and expertise keywords;
- `[[organization.tools]]` for tools and products the center has built; and
- `[[organization.partners]]` for the health departments and health systems the center
  works with.

Use the filename and the `organization.id` as the same stable, lowercase slug whenever
possible. The daily workflow validates every profile before publishing new data.

## Researcher fields

Profile links: `website`, `linkedin`, `github`, `twitter`, `bluesky`, `google_scholar`,
`orcid`, `pubmed`, `europepmc`, `arxiv`, `medrxiv`. All must be `http(s)` URLs.

`orcid` is the one that matters most: it drives publication collection, and the `pubmed`
and `europepmc` links are derived from it automatically when they are not set.

Publication collection also reads:

- `pubmed_query` / `arxiv_query` — opt-in author searches for researchers who have no
  ORCID. Without one of these, a researcher without an ORCID collects no publications,
  which is deliberate: an unqualified name search collects other people's papers.
- `collect_works` — set to `false` to exclude someone from publication collection.

See the repository README for query examples and the full list of publication sources.

## Tool fields

Tools and products are maintained by hand and are not collected automatically, because
centers describe them in prose on their own pages rather than in any machine-readable
feed. Transcribe what a center actually publishes; do not infer a tool from a stated goal.

```toml
[[organization.tools]]
name = "RespiLens"                  # required
summary = "Flexible dashboard for exploring respiratory disease trends."
url = "https://www.respilens.com/"  # where a reader can use it
repository = "https://github.com/..."  # optional source code link
category = "dashboard"              # see below; defaults to "other"
status = "available"                # available | in-development | retired
keywords = ["respiratory disease", "forecasting"]
```

`category` must be one of `dashboard`, `package`, `platform`, `model`, `dataset`,
`application`, or `other`. `id` is generated from the name when omitted and must be
unique within the center.

A tool with no public URL is still worth recording — mark it `status = "in-development"`
so the dashboard labels it honestly. When a center publishes no tools, leave the section
out and add a comment saying so, so the next person knows it was checked rather than
skipped.

## Partner fields

Health partners are the health departments, health agencies, and health systems a center
works with. Like tools, they are maintained by hand from what the center and InsightNet
publish; every center's partners are transcribed from its page on `insightnet.us`.

```toml
[[organization.partners]]
name = "Utah Department of Health and Human Services"  # required
acronym = "UDHHS"
type = "state"                       # see below; defaults to "other"
summary = "Anything a reader needs to interpret the entry."
website = "https://dhhs.utah.gov/"
location = "Utah"                    # state, county, or region
```

`type` must be one of `state`, `local`, `tribal`, `federal`, `healthcare`, or `other`,
recording what kind of health organization the partner is so the dashboard can group a
state agency, a county health department, and a health system without guessing from the
name. `id` is generated from the name when omitted and must be unique within the center.

Use the partner's own official name rather than an abbreviation used in passing, and keep
`website` pointed at the organization's own page. A partner with no public site — some
tribal and interagency groups have none — is still worth recording; leave `website` out
and say so in `summary`.
