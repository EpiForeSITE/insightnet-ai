# Organization profiles

Each `*.toml` file in this directory describes exactly one InsightNet organization.
To update a center, edit only its matching file—there is no shared organization list to
merge or coordinate.

Every profile starts with `[organization]` and may include:

- `[organization.social]` for organization links;
- `[[organization.sources]]` for public collection sources; and
- `[[organization.researchers]]` for member profiles and expertise keywords.

Use the filename and the `organization.id` as the same stable, lowercase slug whenever
possible. The daily workflow validates every profile before publishing new data.
