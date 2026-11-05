"""Encrypted Specification authorization, paging and safe internal transport."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.api.app.services.user_specification_service import (
    SpecificationError, UserSpecificationService,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def directus():
    return SimpleNamespace(
        project=SimpleNamespace(get_project=AsyncMock(return_value={"project_id": "project-1"})),
        get_items=AsyncMock(), _make_api_request=AsyncMock(), base_url="http://cms",
    )


# contract-test: supporting surface=rest_api assertions=contracts.project.encrypted-embed,contracts.links.revision-traceable
@pytest.mark.asyncio
async def test_project_access_denial_precedes_every_storage_operation(monkeypatch):
    cms = directus()
    cms.project.get_project.return_value = None
    service = UserSpecificationService(cms)
    for operation in (
        service.list_specifications("project-1", "other"),
        service.detail("project-1", "spec-1", "other"),
        service.revisions("project-1", "spec-1", "other"),
        service.mutate("create", "project-1", "spec-1", "other", {}),
    ):
        with pytest.raises(SpecificationError, match="project_not_found"):
            await operation
    cms.get_items.assert_not_awaited()
    cms._make_api_request.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=contracts.project.encrypted-embed,contracts.surface.semantic-parity
@pytest.mark.asyncio
async def test_personal_list_binds_project_and_excludes_team_records():
    cms = directus()
    cms.get_items.return_value = [{"specification_id": "spec-1"}, {"specification_id": "spec-2"}]
    result = await UserSpecificationService(cms).list_specifications("project-1", "owner", limit=1, after="spec-0")
    assert result == {"specifications": [{"specification_id": "spec-1"}], "next_cursor": "spec-1"}
    params = cms.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == digest("owner")
    assert params["filter[hashed_team_id][_null]"] is True
    assert params["filter[home_project_hash][_eq]"] == digest("project-1")
    assert params["filter[specification_id][_gt]"] == "spec-0"
    assert params["limit"] == 2
    assert cms.get_items.await_args.kwargs["no_cache"] is True
    assert cms.get_items.await_args.kwargs["raise_on_error"] is True


# contract-test: supporting surface=rest_api assertions=contracts.project.encrypted-embed,contracts.links.revision-traceable
@pytest.mark.asyncio
async def test_missing_or_foreign_head_prevents_revision_lookup():
    cms = directus()
    cms.get_items.return_value = []
    with pytest.raises(SpecificationError, match="specification_not_found"):
        await UserSpecificationService(cms).detail("project-1", "foreign-spec", "owner", revision_id="foreign-revision")
    assert cms.get_items.await_count == 1


# contract-test: supporting surface=rest_api assertions=contracts.revision.optimistic-conflict,contracts.project.encrypted-embed
@pytest.mark.asyncio
async def test_mutation_uses_server_scope_and_preserves_caller_proposal_on_conflict(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-only")
    cms = directus()
    cms._make_api_request.return_value = httpx.Response(409, json={"error": {"code": "revision_conflict"}})
    payload = {"hashed_user_id": "forged", "actor_hash": "forged", "encrypted_specification_document": "cipher-proposal"}
    with pytest.raises(SpecificationError, match="revision_conflict"):
        await UserSpecificationService(cms).mutate("revise", "project-1", "spec-1", "owner", payload)
    actual = cms._make_api_request.await_args.kwargs["json"]
    assert actual["hashed_user_id"] == digest("owner") and actual["actor_hash"] == digest("owner")
    assert actual["hashed_team_id"] is None
    assert payload["encrypted_specification_document"] == "cipher-proposal"
    assert payload["hashed_user_id"] == "forged"


# contract-test: supporting surface=rest_api assertions=contracts.authoring.shared-direct-and-chat,contracts.project.encrypted-embed
@pytest.mark.asyncio
async def test_storage_outage_is_not_reported_as_success_and_does_not_echo_internal_diagnostics(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-only")
    cms = directus()
    cms._make_api_request.return_value = httpx.Response(500, text="private database diagnostic")
    with pytest.raises(SpecificationError) as caught:
        await UserSpecificationService(cms).mutate("create", "project-1", "spec-1", "owner", {})
    assert caught.value.status_code == 503
    assert str(caught.value) == "specification_storage_unavailable"


# contract-test: supporting surface=rest_api assertions=contracts.links.revision-traceable,contracts.revision.exact-approval
@pytest.mark.asyncio
async def test_history_uses_bounded_revision_cursor_and_team_scope():
    cms = directus()
    cms.get_items.side_effect = [[{"specification_id": "spec-1"}], [
        {"revision_number": 3}, {"revision_number": 2}, {"revision_number": 1},
    ]]
    result = await UserSpecificationService(cms).revisions("project-1", "spec-1", "member", team_id="team-1", limit=2, before=4)
    assert result == {"revisions": [{"revision_number": 3}, {"revision_number": 2}], "next_cursor": 2}
    scope = cms.get_items.await_args_list[0].kwargs["params"]
    assert scope["filter[hashed_team_id][_eq]"] == digest("team-1")
    assert scope["filter[hashed_user_id][_null]"] is True
    history = cms.get_items.await_args.kwargs["params"]
    assert history["limit"] == 3 and history["filter[revision_number][_lt]"] == 4
