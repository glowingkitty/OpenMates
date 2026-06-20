"""
Regression tests for short public report issue IDs.

The tests avoid Directus and FastAPI startup. They exercise the deterministic
contract seams used by the settings and admin/debug routes: allowed ID shape,
lookup filter selection, and collision-safe record creation.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.utils.report_issue_ids import (
    SHORT_ISSUE_ID_ALPHABET,
    create_issue_record_with_short_id,
    generate_short_issue_id,
    issue_identifier_filter,
    issue_identifier_query_params,
)


class FakeDirectus:
    def __init__(self, existing_short_ids: set[str] | None = None):
        self.existing_short_ids = existing_short_ids or set()
        self.created_payloads: list[dict] = []

    async def get_items(self, collection: str, params: dict, **_kwargs):
        assert collection == "issues"
        short_id = params.get("filter", {}).get("short_issue_id", {}).get("_eq")
        if short_id and short_id in self.existing_short_ids:
            return [{"id": "existing", "short_issue_id": short_id}]
        return []

    async def create_item(self, collection: str, payload: dict):
        assert collection == "issues"
        self.created_payloads.append(payload)
        return True, {"id": "issue-uuid", **payload}


def test_generate_short_issue_id_uses_allowed_alphabet():
    short_id = generate_short_issue_id()

    assert len(short_id) == 5
    assert set(short_id).issubset(set(SHORT_ISSUE_ID_ALPHABET))
    assert not {"0", "O", "1", "I"}.intersection(short_id)


def test_identifier_filter_selects_uuid_or_short_id():
    uuid = "a3d966e2-3d50-4f3a-b208-31ee218afe12"

    assert issue_identifier_filter(uuid) == {"id": {"_eq": uuid}}
    assert issue_identifier_filter("k7m2q") == {"short_issue_id": {"_eq": "K7M2Q"}}
    assert issue_identifier_query_params("k7m2q") == {"filter[short_issue_id][_eq]": "K7M2Q", "limit": 1}


@pytest.mark.asyncio
async def test_create_issue_record_retries_existing_short_id(monkeypatch):
    candidates = iter(["K7M2Q", "Z8R4T"])
    monkeypatch.setattr("backend.core.api.app.utils.report_issue_ids.generate_short_issue_id", lambda: next(candidates))
    directus = FakeDirectus(existing_short_ids={"K7M2Q"})

    issue = await create_issue_record_with_short_id(directus, {"title": "Bug"})

    assert issue["short_issue_id"] == "Z8R4T"
    assert directus.created_payloads == [{"title": "Bug", "short_issue_id": "Z8R4T"}]


@pytest.mark.asyncio
async def test_create_issue_record_fails_after_short_id_collisions(monkeypatch):
    monkeypatch.setattr("backend.core.api.app.utils.report_issue_ids.SHORT_ISSUE_ID_MAX_ATTEMPTS", 2)
    monkeypatch.setattr("backend.core.api.app.utils.report_issue_ids.generate_short_issue_id", lambda: "K7M2Q")
    directus = FakeDirectus(existing_short_ids={"K7M2Q"})

    with pytest.raises(ValueError, match="unique short issue ID"):
        await create_issue_record_with_short_id(directus, {"title": "Bug"})
