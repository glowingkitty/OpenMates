# backend/tests/test_code_test_result_embed.py
#
# Test result embed: content shape for the three run kinds, evidence by asset id,
# links to tested embeds, creation through EmbedService and staleness refresh.

from __future__ import annotations

import json

import pytest
from toon_format import decode, encode

from backend.apps.code.tasks.test_result_embed import (
    STALE_REASON_REVISIONS_CHANGED,
    apply_currency,
    build_test_result_content,
    create_test_result_embed,
    failure_log_summary,
    refresh_test_result_currency,
)
from backend.shared.python_schemas.code_test_run import ProjectFileRevision

REV = [{"path": "web-app/app.js", "revision": "r1"}]


def _result(kind: str, **extra):
    base = {
        "kind": kind, "target": "e2b", "status": "passed", "exit_code": 0, "duration_ms": 4200,
        "revisions": REV, "passed": 1, "failed": 0, "skipped": 0,
        "tests": [{"name": "works", "status": "passed", "duration_ms": 10}],
        "steps": [], "evidence": [],
    }
    base.update(extra)
    return base


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_unit_content_is_summary_only() -> None:
    content = build_test_result_content(_result("unit"), embed_ref="unit-1", tested_embed_ids=["a", "a", "b"])
    assert content["kind"] == "unit" and content["run_status"] == "passed"
    assert content["tested_embed_ids"] == ["a", "b"]
    assert content["steps"] == [] and content["evidence"] == []
    assert content["is_current"] is True


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_browser_content_keeps_steps_order_and_evidence_asset_ids() -> None:
    result = _result(
        "browser",
        steps=[
            {"name": "Open page", "start_ms": 0, "end_ms": 500, "status": "passed"},
            {"name": "Click add", "start_ms": 500, "end_ms": 900, "status": "passed", "is_preview": True},
        ],
        evidence=[
            {"kind": "video", "path": "outputs/test-run/video.webm", "mime_type": "video/webm", "size_bytes": 10, "asset_id": "asset-v"},
            {"kind": "preview_frame", "path": "outputs/test-run/preview.png", "mime_type": "image/png", "size_bytes": 5, "asset_id": "asset-p", "at_step": 1},
        ],
        preview_step_index=1,
    )
    content = build_test_result_content(result, embed_ref="browser-1")
    assert [s["name"] for s in content["steps"]] == ["Open page", "Click add"]
    assert {e["kind"]: e["asset_id"] for e in content["evidence"]} == {"video": "asset-v", "preview_frame": "asset-p"}
    assert content["preview_step_index"] == 1
    # TOON round trip keeps the structure clients decode.
    decoded = decode(encode(content))
    assert decoded["steps"][1]["is_preview"] is True and decoded["evidence"][0]["asset_id"] == "asset-v"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_cli_content_carries_command_and_output() -> None:
    result = _result(
        "cli",
        steps=[{"name": "add", "start_ms": 0, "end_ms": 5, "status": "passed", "command": "recipes add Pancakes", "output": "Added\nPancakes"}],
        evidence=[{"kind": "terminal_cast", "path": "outputs/test-run/terminal.cast", "mime_type": "application/x-asciicast", "size_bytes": 9, "asset_id": "cast-1"}],
    )
    decoded = decode(encode(build_test_result_content(result, embed_ref="cli-1")))
    assert decoded["steps"][0]["command"] == "recipes add Pancakes"
    assert decoded["steps"][0]["output"] == "Added\nPancakes"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_staleness_follows_result_is_current() -> None:
    content = build_test_result_content(_result("unit"), embed_ref="u")
    same = [ProjectFileRevision(path="web-app/app.js", revision="r1")]
    changed = [ProjectFileRevision(path="web-app/app.js", revision="r2")]
    assert apply_currency(content, same)["is_current"] is True
    stale = apply_currency(content, changed)
    assert stale["is_current"] is False and stale["stale_reason"] == STALE_REASON_REVISIONS_CHANGED


class _Encryption:
    async def encrypt_with_user_key(self, text, key_id):
        return f"enc:{key_id}:{len(text)}", None


class _Redis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True


class _Cache:
    def __init__(self):
        self.redis = _Redis()

    @property
    async def client(self):
        return self.redis


class _FakeEmbedService:
    def __init__(self):
        self.encryption_service = _Encryption()
        self.cache_service = _Cache()
        self.sent: list[dict] = []
        self.cached: dict[str, str] = {}
        self.records: dict[str, dict] = {}
        self.deliver = True

    @staticmethod
    def _generate_direct_embed_ref(kind, embed_id, meta):
        return f"{kind}-{embed_id[:6]}"

    def _schedule_embed_persistence_fallback(self, embed_id):
        pass

    async def send_embed_data_to_client(self, **kwargs):
        self.sent.append(kwargs)
        self.cached[kwargs["embed_id"]] = kwargs["content_toon"]
        self.records[kwargs["embed_id"]] = {"version_number": kwargs.get("version_number") or 1, "message_id": kwargs["message_id"], "created_at": kwargs["created_at"]}
        return self.deliver

    async def _get_cached_embed_toon(self, embed_id, key_id, prefix=""):
        return self.cached.get(embed_id)

    async def _get_embed_record(self, embed_id, prefix=""):
        return self.records.get(embed_id)


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
@pytest.mark.asyncio
async def test_create_links_tested_embeds_and_marks_stale_on_new_revision() -> None:
    service = _FakeEmbedService()
    created = await create_test_result_embed(
        service, result=_result("unit"), chat_id="chat", message_id="msg", user_id="u", user_id_hash="h",
        user_vault_key_id="vk", execution_id="exec", project_id="proj", tested_embed_ids=["code-embed", "app-embed"],
    )
    sent = service.sent[0]
    assert sent["embed_type"] == "test_result" and sent["app_id"] == "code" and sent["skill_id"] == "test_result"
    assert sent["embed_ids"] == ["code-embed", "app-embed"]
    assert sent["finished_cache_data"]["encrypted_content"].startswith("enc:vk:")
    stored = decode(service.cached[created["embed_id"]])
    assert stored["project_id"] == "proj" and stored["revisions"][0]["revision"] == "r1"

    unchanged = [ProjectFileRevision(path="web-app/app.js", revision="r1")]
    kwargs = dict(embed_id=created["embed_id"], chat_id="chat", user_id="u", user_id_hash="h", user_vault_key_id="vk")
    assert await refresh_test_result_currency(service, current_revisions=unchanged, **kwargs) is False
    changed = [ProjectFileRevision(path="web-app/app.js", revision="r2")]
    assert await refresh_test_result_currency(service, current_revisions=changed, **kwargs) is True
    refreshed = decode(service.cached[created["embed_id"]])
    assert refreshed["is_current"] is False and refreshed["version_number"] == 2
    grant = service.cache_service.redis.values[f"embed:{created['embed_id']}:server_owned_refresh"]
    assert json.loads(grant) == {"link_kind": "test_result", "version_number": 2}


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
@pytest.mark.asyncio
async def test_create_raises_when_delivery_fails() -> None:
    service = _FakeEmbedService()
    service.deliver = False
    with pytest.raises(RuntimeError):
        await create_test_result_embed(
            service, result=_result("unit"), chat_id="c", message_id="m", user_id="u", user_id_hash="h", user_vault_key_id="vk",
        )


# contract-test: tooling
def test_failure_log_summary_names_the_failing_step_without_output() -> None:
    long_error = "x" * 500 + "\nsecond line"
    content = build_test_result_content(_result(
        "browser", status="failed", exit_code=1, passed=0, failed=1, error=long_error,
        steps=[{"name": "Open page", "start_ms": 0, "end_ms": 5, "status": "passed"},
               {"name": "Running tests", "start_ms": 5, "end_ms": 9, "status": "failed",
                "error": "Running tests exited with code 1"}],
    ), embed_ref="b-1")
    summary = failure_log_summary(content)
    assert "exit=1" in summary and "failing_step='Running tests'" in summary
    assert "second line" not in summary and "x" * 161 not in summary
    assert failure_log_summary(build_test_result_content(_result("unit"), embed_ref="u-1")) == ""


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_final_result_pairs_each_evidence_with_its_stored_asset_and_variant() -> None:
    from backend.apps.code.tasks.test_run_execution import final_test_result
    from backend.shared.providers.e2b_test_runner import TestRunOutcome
    from backend.shared.python_schemas.code_test_run import TestRunResult

    result = TestRunResult.model_validate(_result("browser", evidence=[
        {"kind": "video", "path": "outputs/test-run/video.webm", "mime_type": "video/webm", "size_bytes": 10},
        {"kind": "trace", "path": "outputs/test-run/trace.zip", "mime_type": "application/zip", "size_bytes": 3},
    ]))
    outcome = TestRunOutcome(result=result, artifacts=[], skipped_artifacts=[], sandbox_id=None,
                             duration_seconds=1.0, output_truncated=False)
    stored = [{"asset_id": "embed-1", "normalized_path": "outputs/test-run/video.webm", "variant": "video-abc"}]
    evidence = final_test_result(outcome, stored)["evidence"]
    assert evidence[0]["asset_id"] == "embed-1" and evidence[0]["variant"] == "video-abc"
    # Evidence whose storage failed carries neither, so clients show "no video".
    assert evidence[1]["asset_id"] is None and evidence[1]["variant"] is None
