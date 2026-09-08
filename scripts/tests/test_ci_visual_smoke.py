# contract-test-file: tooling
"""Validate isolated screenshot transport without executing a browser.

Keep preview targets bounded and bind both original-script screenshots.
Transport success must never invent agent review or user approval evidence.
Queue identity and internal runtime isolation reuse the existing coordinator.
These deterministic tests do not access Docker, accounts or external services.
"""
import json
from types import SimpleNamespace

import pytest
from scripts import ci_visual_smoke as smoke
from scripts.ci_coordinator import Queue
from scripts.ci_environment import compose_profile

URL = "http://localhost:5173/dev/preview/tasks/TaskDetailFullscreen?chrome=0"


@pytest.mark.parametrize("url", [
    "https://app.dev.openmates.org/dev/preview/tasks/TaskDetailFullscreen?chrome=0",
    URL.replace("localhost", "127.0.0.1"), URL.replace("chrome=0", "chrome=1"),
    URL + "&props=secret", URL + "#fragment", URL.replace("tasks/", "../"),
    URL.replace("tasks/", "%2e%2e/"), "http://localhost:5173/settings",
])
def test_targets_reject_nondefault_or_external_urls(url):
    with pytest.raises(ValueError):
        smoke.validate_targets([url])


def test_queue_uses_existing_identity_and_rejects_video_override(tmp_path):
    queue = Queue(tmp_path / "queue.sqlite")
    job = queue.enqueue("ecad", "a" * 40, [URL], "visual-smoke")
    assert job["state"] == "queued"
    assert queue.enqueue("ecad", "a" * 40, [URL], "visual-smoke")["id"] == job["id"]
    with pytest.raises(ValueError):
        queue.enqueue("ecad", "a" * 40, [URL], "visual-smoke", proof_profile="web-phone")
    with pytest.raises(ValueError):
        queue.enqueue("ecad", "a" * 40, [], "visual-smoke")


def test_preview_runtime_has_internal_network_without_ai_fixtures():
    profile = compose_profile("a" * 40, offline_preview=True, account_emails=[])
    assert profile["networks"]["default"]["internal"] is True
    assert "ai-worker" not in profile["services"]
    assert "OPENMATES_CI_AI_FIXTURES" not in profile["services"]["api"]["environment"]


def test_original_capture_retains_both_images_and_requires_agent_review(tmp_path, monkeypatch):
    def run(command, **kwargs):
        assert command[:2] == ["node", str(tmp_path / "scripts/visual-smoke.mjs")]
        assert "--session" not in command and "--reviewed-summary" not in command
        assert kwargs["timeout"] == 300
        out = tmp_path / "ci-visual-smoke"
        records = []
        for viewport in sorted(smoke.VIEWPORTS):
            path = out / f"preview-{viewport}.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-tooling-fixture")
            records.append({"url": URL, "viewport": viewport, "screenshot": str(path), "problems": []})
        (out / "summary.json").write_text(json.dumps({"method": "playwright", "urls": [URL],
            "viewports": sorted(smoke.VIEWPORTS), "records": records, "result": "passed"}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(smoke.subprocess, "run", run)
    results = smoke.capture([URL], tmp_path, tmp_path)
    assert results[0]["exit_code"] == 0
    assert results[0]["visual_review"] == "pending"
    receipt = smoke.verify_capture(tmp_path / "ci-visual-smoke", [URL])
    assert receipt["review_status"] == "pending"
    (tmp_path / "ci-visual-smoke/preview-mobile.png").write_bytes(b"\x89PNG\r\n\x1a\ntampered")
    with pytest.raises(ValueError, match="receipt mismatch"):
        smoke.verify_capture(tmp_path / "ci-visual-smoke", [URL])
