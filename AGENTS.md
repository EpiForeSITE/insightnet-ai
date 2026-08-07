# Contributor protocol

## Commit trailer

Any commit created by Codex in this repository must include this Git trailer:

```text
Co-authored-by: OpenAI Codex <noreply@openai.com>
```

This applies to the initial commit and to all later Codex-assisted commits.

## Versioning

**Every change bumps the version.** There is no such thing as a change too small to
version here — the site footer shows the version and links to the release notes, so a
number that did not move tells readers nothing shipped.

The version lives in exactly one place:

```python
# insightnet/__init__.py
__version__ = "1.0.0"
```

`pyproject.toml` reads it through `[tool.setuptools.dynamic]`, the GitHub Pages
deployment substitutes it into the `__APP_VERSION__` placeholder in `site/index.html`,
and each release is tagged `v<version>`. **Never write a version number anywhere else.**
Do not put a literal into the footer, a comment, or the docs; a test enforces this.

### Choosing the part to bump

The scheme is `major.minor.patch`.

| Part | Bump it when | Examples |
|---|---|---|
| **major** | The change breaks something people depend on, or the site's purpose or shape changes | Removing a view or a published JSON field; renaming a data file; changing what a URL means |
| **minor** | Something new arrives and everything that worked still works | A new view, a new filter, a new collection source, a new field added to a snapshot |
| **patch** | A defect is corrected, or something is tidied with no change in behavior | A search returning wrong results; a broken link; wording, styling, comments, refactors, and test-only changes |

Bump only the highest part that applies and reset the parts to its right: a new feature
on `1.4.2` gives `1.5.0`, not `1.5.2`. Bump once for the whole change, not once per
commit within it.

When in doubt between two parts, pick the larger one and say so in the commit message.
Under-versioning a breaking change is the costly mistake; over-versioning is free.

### With the bump

1. Edit `__version__` in `insightnet/__init__.py`.
2. Run `uv lock` — the lock file records the project version and will otherwise drift.
3. Run `uv run pytest`.

Do not create the git tag or the GitHub release yourself unless you were asked to; that
is a publishing step, and the maintainer decides when it happens.
