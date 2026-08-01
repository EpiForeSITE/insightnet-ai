# Organization profiles

Each `*.toml` file in this directory describes exactly one InsightNet organization.
To update a center, edit only its matching file—there is no shared organization list to
merge or coordinate.

Every profile starts with `[organization]` and may include:

- `[organization.social]` for organization links;
- `[[organization.sources]]` for public collection sources;
- `[[organization.researchers]]` for member profiles and expertise keywords; and
- `[[organization.tools]]` for tools and products the center has built.

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
