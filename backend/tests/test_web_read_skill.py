"""Offline contracts for generic public-page reading and complete saved payloads."""
from copy import deepcopy
import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.apps.web.skills import read_skill as reader


@pytest.fixture
def skill(monkeypatch):
    instance = reader.ReadSkill(app=None, app_id="web", skill_id="read", skill_name="Read", skill_description="Read public pages", pricing_config={"per_unit": {"credits": 20, "unit_name": "page"}})
    monkeypatch.setattr(reader, "is_central_app_skill_dispatch", lambda: False)

    async def sanitize(payload, context):
        return payload

    monkeypatch.setattr(reader, "sanitize_app_skill_output", sanitize)
    return instance


def page(url="https://example.test/article", markdown="Complete article text"):
    return {"url": url, "source_url": url, "title": "Article", "markdown": markdown,
            "language": "en", "favicon": "https://example.test/favicon.ico",
            "og_image": "https://example.test/image.png", "og_sitename": "Example",
            "http_status": 200, "warnings": [], "read_status": "ok"}


# contract-test: supporting surface=rest_api assertions=web-read.public-page,web-read.saved-full-text,app-skills.output.external-semantic
@pytest.mark.asyncio
async def test_full_markdown_metadata_hash_and_direct_safety_survive(skill, monkeypatch):
    markdown = "# Full page\n" + ("Complete paragraph with café and 日本語.\n" * 9000)
    fetch = AsyncMock(return_value=page("https://example.test/final", markdown))
    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    seen = []

    async def sanitize(payload, context):
        seen.append((deepcopy(payload), context))
        payload["results"][0]["results"][0]["title"] = "Scanned article"
        return payload

    monkeypatch.setattr(reader, "sanitize_app_skill_output", sanitize)
    result = await skill.execute(requests=[{"id": "page-1", "url": "https://example.test/article#section"}])
    assert result.error is None
    assert result.results[0]["id"] == "page-1"
    item = result.results[0]["results"][0]
    assert item["markdown"] == markdown
    assert item["markdown"].endswith("Complete paragraph with café and 日本語.\n")
    assert item["title"] == "Scanned article"
    assert item["source_url"] == "https://example.test/final"
    assert item["url"] == "https://example.test/article"
    assert item["type"] == "read_result"
    assert item["hash"] == skill._generate_result_hash(item["url"])
    assert item["language"] == "en" and item["og_sitename"] == "Example"
    assert item["favicon"] and item["og_image"]
    assert len(seen) == 1
    assert seen[0][0]["results"][0]["results"][0]["markdown"] == markdown
    assert seen[0][1].external_data is True
    assert seen[0][1].app_id == "web" and seen[0][1].skill_id == "read"
    assert "markdown" not in result.ignore_fields_for_inference


# contract-test: supporting surface=rest_api assertions=web-read.crawler-exclusions,web-read.public-page
@pytest.mark.asyncio
async def test_blocked_page_stays_visible_without_poisoning_successful_sibling(skill, monkeypatch):
    seen = []

    async def fetch(url, **kwargs):
        seen.append(url)
        if url.endswith("blocked"):
            raise reader.PublicWebReadError("robots_denied", "The site excludes this crawler.", 403)
        return page(url)

    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    result = await skill.execute(requests=[{"id": "blocked", "url": "https://example.test/blocked"},
                                           {"id": "allowed", "url": "https://example.test/allowed"}])
    assert [group["id"] for group in result.results] == ["blocked", "allowed"]
    blocked, allowed = result.results
    assert blocked["results"] == []
    assert blocked["read_status"] == "robots_denied" and blocked["http_status"] == 403
    assert blocked["error"] == "The site excludes this crawler."
    assert allowed["results"][0]["markdown"] == "Complete article text"
    assert blocked["usage"]["credits_charged"] == 0
    assert allowed["usage"]["credits_charged"] == 20
    assert result.error is None
    assert result.warnings == ["The site excludes this crawler."]
    assert seen == ["https://example.test/blocked", "https://example.test/allowed"]


# contract-test: supporting surface=rest_api assertions=web-read.public-page,web-read.transport-boundary
@pytest.mark.asyncio
async def test_fresh_reads_ignore_legacy_max_age_without_loading_credentials(skill, monkeypatch):
    fetch = AsyncMock(side_effect=[page(markdown="First version"), page(markdown="Fresh version")])
    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    credentials = AsyncMock(side_effect=AssertionError("Reader transport needs no credentials"))
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", credentials)
    request = {"url": "https://example.test/article", "max_age": 172800000,
               "formats": ["markdown"], "only_main_content": False, "timeout": 30000}
    first = await skill.execute(requests=[request])
    second = await skill.execute(requests=[request])
    assert first.results[0]["results"][0]["markdown"] == "First version"
    assert second.results[0]["results"][0]["markdown"] == "Fresh version"
    assert fetch.await_count == 2
    assert all(call.kwargs == {"only_main_content": False, "timeout_ms": 30000} for call in fetch.await_args_list)
    credentials.assert_not_awaited()
    assert "id" not in request  # Caller input is not mutated by generated IDs.


# contract-test: supporting surface=rest_api assertions=web-read.transport-boundary
@pytest.mark.asyncio
@pytest.mark.parametrize("requests", [[], [{"url": "https://example.test"}] * 6])
async def test_batch_bounds_fail_before_transport(skill, monkeypatch, requests):
    fetch = AsyncMock(side_effect=AssertionError("Invalid batch must not access transport"))
    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    result = await skill.execute(requests=requests)
    assert result.results == [] and "one and five" in result.error
    fetch.assert_not_awaited()
    with pytest.raises(ValidationError):
        reader.ReadRequest(requests=requests)


# contract-test: supporting surface=rest_api assertions=web-read.public-page,web-read.transport-boundary
@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{"formats": ["html"]}, {"formats": ["summary"]}, {"timeout": 999}, {"timeout": 30001}, {"max_age": -1}])
async def test_unsupported_formats_and_timeouts_fail_before_transport(skill, monkeypatch, fields):
    fetch = AsyncMock(side_effect=AssertionError("Invalid item must not access transport"))
    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    result = await skill.execute(requests=[{"url": "https://example.test/article", **fields}])
    assert result.results[0]["results"] == []
    assert result.results[0]["read_status"] == "invalid_request"
    fetch.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-read.public-page
@pytest.mark.asyncio
async def test_missing_url_is_a_group_error_and_ids_remain_stable(skill, monkeypatch):
    fetch = AsyncMock(return_value=page())
    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    result = await skill.execute(requests=[{"id": "missing"}, {"id": 42, "url": "https://example.test/article"}])
    assert [group["id"] for group in result.results] == ["missing", 42]
    assert result.results[0]["read_status"] == "invalid_request"
    assert result.results[1]["results"][0]["markdown"] == "Complete article text"
    fetch.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-read.transport-boundary
@pytest.mark.asyncio
async def test_batch_deadline_cancels_pending_fetch_and_keeps_completed_page(skill, monkeypatch):
    cancelled = asyncio.Event()

    async def fetch(url, **kwargs):
        if url.endswith("slow"):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return page(url)

    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    monkeypatch.setattr(reader, "READ_BATCH_TIMEOUT_SECONDS", 0.02)
    result = await skill.execute(requests=[{"id": "fast", "url": "https://example.test/fast"},
                                           {"id": "slow", "url": "https://example.test/slow"}])
    assert result.results[0]["results"][0]["markdown"] == "Complete article text"
    assert result.results[1]["results"] == [] and result.results[1]["read_status"] == "timeout"
    assert cancelled.is_set()


# contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic,web-read.saved-full-text
@pytest.mark.asyncio
async def test_central_dispatch_keeps_the_shared_output_safety_owner(skill, monkeypatch):
    monkeypatch.setattr(reader, "read_public_web_page", AsyncMock(return_value=page()))
    monkeypatch.setattr(reader, "is_central_app_skill_dispatch", lambda: True)
    sanitize = AsyncMock(side_effect=AssertionError("Central dispatch owns the one output scan"))
    monkeypatch.setattr(reader, "sanitize_app_skill_output", sanitize)
    result = await skill.execute(requests=[{"url": "https://example.test/article"}])
    assert result.results[0]["results"][0]["markdown"] == "Complete article text"
    sanitize.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-read.public-page,web-read.crawler-exclusions
@pytest.mark.asyncio
@pytest.mark.parametrize("paths", [["allowed"], ["allowed", "blocked"], ["blocked"]])
async def test_direct_execution_never_mints_creator_income_before_a_committed_charge(skill, monkeypatch, paths):
    from backend.core.api.app.services.creators import revenue_service
    from backend.core.api.app.utils import server_mode

    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    create = AsyncMock(side_effect=AssertionError("An unbilled direct read must not create creator income"))
    monkeypatch.setattr(revenue_service.CreatorRevenueService, "create_income_entry", create)
    assert skill.pricing.per_unit.credits == 20

    async def fetch(url, **kwargs):
        if url.endswith("blocked"):
            raise reader.PublicWebReadError("robots_denied", "Crawler excluded.")
        return page(url)

    monkeypatch.setattr(reader, "read_public_web_page", fetch)
    result = await skill.execute(
        requests=[{"url": f"https://example.test/{path}"} for path in paths],
        # User-supplied hints are not an authoritative server charge receipt.
        charge_receipt={"status": "success", "state": "committed", "charged_credits": 20,
                        "charge_id": "caller-forged"},
    )
    assert [group["usage"]["credits_charged"] for group in result.results] == [20 if path == "allowed" else 0 for path in paths]
    assert bool(result.error) == all(path == "blocked" for path in paths)
    create.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-read.public-page,app-skills.execution.registered-validated
def test_restored_reader_workflow_classification_uses_current_metadata():
    from pathlib import Path
    from backend.core.api.app.services.workflow_capability_registry import (
        WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
    )

    metadata = _FilesystemWorkflowMetadataRegistry(apps_root=Path(reader.__file__).resolve().parents[2])
    assert metadata.is_skill_available("web", "read")
    capability = WorkflowCapabilityRegistry(skill_registry=metadata).get_capability("web.read")
    assert capability.enabled is True and capability.reason is None
    workflow = capability.metadata["workflow"]
    assert workflow["execution_mode"] == "sync" and workflow["effect"] == "read"
    assert workflow["approval"] == "never" and workflow["binding_requirements"] == ["none"]
    assert workflow["test_example_input"]["requests"][0]["formats"] == ["markdown"]
