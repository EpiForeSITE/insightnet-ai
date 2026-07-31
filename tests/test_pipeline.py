from insightnet.collectors import CollectionResult
from insightnet.pipeline import build_snapshot


def test_pipeline_isolates_sources_and_links_items(monkeypatch) -> None:
    profiles = {
        "network": {"name": "Test"},
        "organizations": [
            {
                "id": "alpha",
                "name": "Alpha",
                "summary": "Disease modeling group",
                "focus_areas": ["epidemiology"],
                "keywords": [],
                "researchers": [],
                "sources": [
                    {"type": "rss", "label": "News", "enabled": True},
                    {"type": "website", "label": "Broken", "enabled": True},
                ],
            }
        ],
    }

    def fake_collect(_client, source):
        if source["label"] == "Broken":
            return CollectionResult(status="error", message="timeout")
        return CollectionResult(
            message="ok",
            items=[
                {
                    "title": "Modeling an outbreak",
                    "url": "https://example.org/article",
                    "summary": "A useful model",
                    "published_at": "2026-01-01T00:00:00Z",
                    "authors": [],
                    "keywords": ["modeling"],
                }
            ],
        )

    monkeypatch.setattr("insightnet.pipeline.collect_source", fake_collect)
    snapshot = build_snapshot(profiles, client=object())

    assert snapshot["stats"]["items"] == 1
    assert snapshot["stats"]["sources_attention"] == 1
    assert snapshot["items"][0]["organization_id"] == "alpha"
    assert snapshot["organizations"][0]["activity_count"] == 1
    assert [row["status"] for row in snapshot["health"]] == ["ok", "error"]


def test_scholar_source_is_derived_from_researcher(monkeypatch) -> None:
    seen = []
    profiles = {
        "network": {},
        "organizations": [
            {
                "id": "alpha",
                "name": "Alpha",
                "summary": "",
                "focus_areas": [],
                "keywords": [],
                "sources": [],
                "researchers": [
                    {
                        "id": "person",
                        "full_name": "A Person",
                        "bio": "",
                        "expertise": ["networks"],
                        "keywords": [],
                        "scholar_author_id": "abc123",
                    }
                ],
            }
        ],
    }

    def fake_collect(_client, source):
        seen.append(source)
        return CollectionResult(status="skipped", message="no key")

    monkeypatch.setattr("insightnet.pipeline.collect_source", fake_collect)
    snapshot = build_snapshot(profiles, client=object())

    assert seen[0]["type"] == "google_scholar"
    assert seen[0]["author_id"] == "abc123"
    assert snapshot["health"][0]["status"] == "skipped"


def test_pipeline_retains_previous_items(monkeypatch) -> None:
    profiles = {
        "network": {"retention_days": 730, "max_items_per_organization": 100},
        "organizations": [
            {
                "id": "alpha",
                "name": "Alpha",
                "summary": "",
                "focus_areas": [],
                "keywords": [],
                "sources": [{"type": "rss", "label": "News", "enabled": True}],
                "researchers": [],
            }
        ],
    }
    previous = {
        "items": [
            {
                "id": "old-item",
                "organization_id": "alpha",
                "title": "Still useful",
                "published_at": "2026-01-01T00:00:00Z",
                "first_seen_at": "2026-01-02T00:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(
        "insightnet.pipeline.collect_source", lambda *_args: CollectionResult(message="ok")
    )

    snapshot = build_snapshot(profiles, client=object(), previous_snapshot=previous)

    assert [item["id"] for item in snapshot["items"]] == ["old-item"]
    assert snapshot["organizations"][0]["activity_count"] == 1
