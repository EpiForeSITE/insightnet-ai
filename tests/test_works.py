import pytest

from insightnet import works
from insightnet.works import (
    WorksResult,
    _finalize_type,
    _merge_into,
    _merge_works_history,
    _normalize_arxiv_id,
    _normalize_doi,
    _split_venue,
    _work_record,
    build_works_snapshot,
    is_citable,
    work_keys,
)


def _profiles(researcher: dict) -> dict:
    return {
        "network": {"max_works_per_researcher": 10, "works_retention_years": 50},
        "organizations": [
            {
                "id": "alpha",
                "name": "Alpha",
                "researchers": [
                    {
                        "id": "person",
                        "full_name": "A Person",
                        "orcid_id": "",
                        "pubmed_query": "",
                        "arxiv_query": "",
                        "collect_works": True,
                        **researcher,
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://doi.org/10.1/AB", "10.1/ab"),
        ("doi: 10.1101/2024.01.01.24300001", "10.1101/2024.01.01.24300001"),
        ("not-a-doi", ""),
    ],
)
def test_doi_normalization(value: str, expected: str) -> None:
    assert _normalize_doi(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("arXiv:2401.12345v2", "2401.12345"),
        ("https://arxiv.org/abs/2401.12345", "2401.12345"),
        ("10.48550/arXiv.2507.07227", "2507.07227"),
        ("q-bio.PE/0701001", "q-bio.PE/0701001"),
        ("10.1016/j.epidem.2026.100885", ""),
    ],
)
def test_arxiv_id_normalization(value: str, expected: str) -> None:
    assert _normalize_arxiv_id(value) == expected


def test_arxiv_doi_is_classified_as_a_preprint() -> None:
    record = _work_record(title="Preprint", doi="10.48550/arXiv.2509.07013", source="orcid")
    assert record["arxiv_id"] == "2509.07013"
    assert record["type"] == "preprint"
    assert record["preprint_server"] == "arXiv"


def test_merge_prefers_precise_dates_and_richer_author_lists() -> None:
    target = _work_record(
        title="A study", published_at="2025-01-01", authors=["Solo Author"], source="orcid"
    )
    extra = _work_record(
        title="A study",
        published_at="2025-09-06",
        abstract="Full abstract",
        authors=["First Author", "Second Author"],
        source="arxiv",
    )

    merged = _merge_into(target, extra)

    assert merged["published_at"] == "2025-09-06"
    assert merged["author_count"] == 2
    assert merged["abstract"] == "Full abstract"
    assert merged["sources"] == ["orcid", "arxiv"]


def test_published_version_outranks_its_preprint() -> None:
    """A preprint merged with its journal version is reported as the article."""

    preprint = _work_record(
        title="A study", doi="10.48550/arXiv.2501.00001", preprint_server="arXiv", source="arxiv"
    )
    published = _work_record(
        title="A study",
        doi="10.1039/d5na00416k",
        pmid="41180127",
        venue="Nanoscale Advances",
        source="europepmc",
    )

    record = _finalize_type(_merge_into(preprint, published))

    assert record["type"] == "article"
    assert record["venue"] == "Nanoscale Advances"
    # Provenance is kept even though the record is reported as the published article.
    assert record["preprint_server"] == "arXiv"


def test_a_preprint_indexed_in_pubmed_is_still_a_preprint() -> None:
    """medRxiv preprints are assigned PubMed IDs, which must not promote them."""

    record = _work_record(
        title="A preprint",
        doi="10.1101/2024.01.01.24300001",
        pmid="12345678",
        preprint_server="medRxiv",
    )
    assert _finalize_type(record)["type"] == "preprint"


def test_a_journal_title_naming_a_preprint_server_is_not_a_venue() -> None:
    venue, server = _split_venue("medRxiv : the preprint server for health sciences")
    assert (venue, server) == ("", "medRxiv")
    assert _split_venue("Nanoscale Advances") == ("Nanoscale Advances", "")


def test_records_with_no_identifier_or_link_are_dropped() -> None:
    assert not is_citable(_work_record(title="A software repository"))
    assert is_citable(_work_record(title="A paper", doi="10.1/ab"))
    assert is_citable(_work_record(title="A report", url="https://example.org/report"))


def test_work_keys_allow_recognizing_a_record_by_any_identifier() -> None:
    record = _work_record(title="Title Here!", doi="10.1/ab", pmid="123456")
    assert work_keys(record) == ["doi:10.1/ab", "pmid:123456", "title:titlehere"]


def test_history_keeps_previous_works_and_stable_ids() -> None:
    previous = {
        "works": [
            {
                "id": "stable-id",
                "title": "Older paper",
                "doi": "10.1/older",
                "year": 2020,
                "published_at": "2020-01-01",
                "first_seen_at": "2020-02-02T00:00:00Z",
                "researcher_ids": ["person"],
            }
        ]
    }
    incoming = _work_record(title="Older paper", doi="10.1/older", published_at="2020-05-05")
    incoming["researcher_ids"] = ["person"]

    merged = _merge_works_history([incoming], previous, "2026-08-01T00:00:00Z", 50, 10)

    assert len(merged) == 1
    assert merged[0]["id"] == "stable-id"
    assert merged[0]["first_seen_at"] == "2020-02-02T00:00:00Z"
    assert merged[0]["last_seen_at"] == "2026-08-01T00:00:00Z"


def test_history_carries_forward_earlier_enrichment() -> None:
    """A run that could not reach an enrichment source must not regress a record."""

    previous = {
        "works": [
            {
                "id": "stable-id",
                "title": "A paper",
                "doi": "10.1/ab",
                "abstract": "Enriched last week",
                "authors": [{"name": "First", "orcid": ""}, {"name": "Second", "orcid": ""}],
                "keywords": ["forecasting"],
                "year": 2025,
                "published_at": "2025-01-01",
                "first_seen_at": "2025-02-02T00:00:00Z",
                "researcher_ids": ["person"],
            }
        ]
    }
    incoming = _work_record(title="A paper", doi="10.1/ab", published_at="2025-03-04")
    incoming["researcher_ids"] = ["person"]

    merged = _merge_works_history([incoming], previous, "2026-08-01T00:00:00Z", 50, 10)

    assert merged[0]["abstract"] == "Enriched last week"
    assert merged[0]["author_count"] == 2
    assert merged[0]["keywords"] == ["forecasting"]
    # Fresh data still wins where this run actually had a value.
    assert merged[0]["published_at"] == "2025-03-04"


def test_history_drops_works_outside_the_retention_window() -> None:
    old = _work_record(title="Ancient", doi="10.1/ancient", published_at="1990-01-01")
    old["researcher_ids"] = ["person"]
    recent = _work_record(title="Recent", doi="10.1/recent", published_at="2025-01-01")
    recent["researcher_ids"] = ["person"]

    merged = _merge_works_history([old, recent], None, "2026-08-01T00:00:00Z", 15, 10)

    assert [work["title"] for work in merged] == ["Recent"]


def test_history_caps_works_per_researcher() -> None:
    works = []
    for year in range(2000, 2026):
        record = _work_record(
            title=f"Paper {year}", doi=f"10.1/{year}", published_at=f"{year}-01-01"
        )
        record["researcher_ids"] = ["person"]
        works.append(record)

    merged = _merge_works_history(works, None, "2026-08-01T00:00:00Z", 50, 5)

    assert len(merged) == 5
    assert [work["year"] for work in merged] == [2025, 2024, 2023, 2022, 2021]


def test_name_search_is_opt_in(monkeypatch) -> None:
    """A researcher with no ORCID and no explicit query is never searched by name."""

    monkeypatch.setattr("insightnet.works.enrich_works", lambda *_args: {})
    snapshot = build_works_snapshot(_profiles({}), client=object())

    statuses = {row["source_type"]: row["status"] for row in snapshot["health"]}
    assert statuses == {
        "works_europepmc": "skipped",
        "works_orcid": "skipped",
        "works_pubmed": "skipped",
        "works_arxiv": "skipped",
    }
    assert snapshot["works"] == []


def test_a_shared_work_lists_every_coauthor_in_the_network(monkeypatch) -> None:
    profiles = {
        "network": {},
        "organizations": [
            {
                "id": "alpha",
                "name": "Alpha",
                "researchers": [
                    {"id": "first", "full_name": "First", "orcid_id": "0000-0000-0000-0001"},
                    {"id": "second", "full_name": "Second", "orcid_id": "0000-0000-0000-0002"},
                ],
            }
        ],
    }

    def fake_collect(_client, researcher, _limits):
        if not researcher.get("orcid_id"):
            return WorksResult(status="skipped")
        return WorksResult(
            works=[
                _work_record(
                    title="Joint paper",
                    doi="10.1/joint",
                    published_at="2025-01-01",
                    authors=["First", "Second"],
                    source="europepmc",
                )
            ]
        )

    monkeypatch.setattr("insightnet.works.collect_europepmc_by_orcid", fake_collect)
    monkeypatch.setattr(
        "insightnet.works.WORK_COLLECTORS", (("europepmc", "Europe PMC", fake_collect),)
    )
    monkeypatch.setattr("insightnet.works.enrich_works", lambda *_args: {})

    snapshot = build_works_snapshot(profiles, client=object())

    assert len(snapshot["works"]) == 1
    assert snapshot["works"][0]["researcher_ids"] == ["first", "second"]
    assert snapshot["stats"]["researchers_with_works"] == 2
    assert snapshot["works_per_researcher"] == {"first": 1, "second": 1}


def test_source_failures_are_isolated_per_researcher(monkeypatch) -> None:
    def exploding(_client, _researcher, _limits):
        raise ValueError("upstream is down")

    monkeypatch.setattr(
        "insightnet.works.WORK_COLLECTORS",
        (
            ("europepmc", "Europe PMC", exploding),
            (
                "orcid",
                "ORCID record",
                lambda *_a: WorksResult(works=[_work_record(title="Kept", doi="10.1/kept")]),
            ),
        ),
    )
    monkeypatch.setattr("insightnet.works.enrich_works", lambda *_args: {})

    snapshot = build_works_snapshot(_profiles({"orcid_id": "0000-0000-0000-0001"}), client=object())

    statuses = {row["source_type"]: row["status"] for row in snapshot["health"]}
    assert statuses["works_europepmc"] == "error"
    assert statuses["works_orcid"] == "ok"
    assert [work["title"] for work in snapshot["works"]] == ["Kept"]
    assert snapshot["stats"]["sources_attention"] == 1


def test_split_and_merge_round_trip_a_works_snapshot() -> None:
    """The published pair must recombine into exactly what was collected.

    The weekly run merges into the previous snapshot, so a lossy split would quietly
    erase every retained abstract and coauthor list one run at a time.
    """

    snapshot = {
        "schema_version": 3,
        "generated_at": "2026-01-01T00:00:00Z",
        "stats": {"works": 2},
        "works": [
            {
                "id": "one",
                "title": "A paper",
                "abstract": "Something worth reading.",
                "authors": [{"name": "Jane Q. Researcher", "orcid": ""}],
                "researcher_ids": ["jane"],
            },
            {
                "id": "two",
                "title": "A record with no abstract",
                "abstract": "",
                "authors": [],
                "researcher_ids": [],
            },
        ],
    }

    index, details = works.split_works_snapshot(snapshot)

    assert [work["id"] for work in index["works"]] == ["one", "two"]
    assert index["stats"] == snapshot["stats"]
    assert all("abstract" not in work and "authors" not in work for work in index["works"])
    assert [work["has_abstract"] for work in index["works"]] == [True, False]
    assert set(details["details"]) == {"one"}

    assert works.merge_works_snapshot(index, details) == snapshot


def test_merging_without_a_detail_document_still_returns_whole_records() -> None:
    """A missing or unreadable detail file must not produce half-formed works."""

    index = {
        "schema_version": 3,
        "works": [{"id": "one", "title": "A paper", "has_abstract": True}],
    }

    merged = works.merge_works_snapshot(index, None)

    assert merged["works"] == [{"id": "one", "title": "A paper", "abstract": "", "authors": []}]
    assert works.merge_works_snapshot(None, None) is None
