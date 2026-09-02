#!/usr/bin/env python3
"""
Regression tests for phone proof-video Safari rendering.

These focused tests keep the phone web proof source at the encoded Safari
content viewport while the final Remotion tutorial renders as a full iPhone
Safari frame. They intentionally avoid the broad account-policy/control-plane
test files that are frequently touched by parallel sessions.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# contract-test-file: tooling


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_DEMO_PATH = PROJECT_ROOT / "scripts" / "spec_demo.py"
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_tests_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_module(TESTS_CONTROL_PATH, "openmates_phone_proof_tests_control")
    results_dir = tmp_path / "test-results"
    monkeypatch.setattr(module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(module, "CONTROL_PLANE_RESULTS_DIR", results_dir)
    monkeypatch.setattr(module, "PROOF_SOURCE_DIR", results_dir / "proof-video-sources")
    monkeypatch.setattr(module, "STATE_FILE", results_dir / "tests-state.json")
    monkeypatch.setattr(module, "HISTORY_FILE", results_dir / "tests-history.jsonl")
    monkeypatch.setattr(module, "LEASES_FILE", results_dir / "failed-test-leases.json")
    monkeypatch.setattr(module, "TRIAGE_FILE", results_dir / "test-failure-triage.json")
    monkeypatch.setattr(module, "TEST_FILE_INDEX_FILE", results_dir / "test-file-index.json")
    monkeypatch.setattr(module, "RESPONSE_MEDIA_LATEST_FILE", results_dir / "response-media-latest.json")
    monkeypatch.setattr(module, "RUNS_DIR", results_dir / "runs")
    monkeypatch.setattr(module, "LEASE_LOCK_FILE", tmp_path / "leases.lock")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "SPEC_DIR", tmp_path / "frontend" / "apps" / "web_app" / "tests")
    monkeypatch.setattr(module, "TEST_STORE", module.InMemoryTestControlStore())
    return module


def write_phone_timeline(module, tmp_path: Path, *, commit: str, video: Path) -> tuple[Path, Path]:
    frame = tmp_path / "phone-checkpoint.png"
    frame.write_bytes(b"frame")
    timeline = tmp_path / "proof-timeline.json"
    timeline.write_text(json.dumps({
        "schema_version": 1,
        "device": "web-phone",
        "contract": {
            "id": "proof-video-web-phone",
            "title": "Proof web phone",
            "surface": "web",
            "devices": ["web-phone"],
            "domain": "app.dev.openmates.org",
            "tutorial": {"readingWordsPerSecond": 2.5, "minimumHoldMs": 1800, "maximumHoldMs": 5000},
            "transcript": [{"id": "phone", "text": "Phone content is visible.", "checkpoint": "phone-ready", "devices": ["web-phone"]}],
            "assertions": [
                {"id": "phone.visible", "visual": "The phone state is visible inside Safari chrome.", "checkpoint": "phone-ready", "devices": ["web-phone"]},
            ],
        },
        "events": [
            {"kind": "checkpoint", "id": "phone-ready", "at_ms": 100},
        ],
        "assertion_results": [{"id": "phone.visible", "status": "passed", "at_ms": 80}],
        "checkpoint_frames": [{"checkpoint": "phone-ready", "path": str(frame), "sha256": module._file_sha256(frame)}],
    }), encoding="utf-8")
    run_artifact = module.RESULTS_DIR / "last-run.json"
    run_artifact.parent.mkdir(parents=True)
    run_artifact.write_text(json.dumps({
        "run_id": "phone-run",
        "git_sha": commit,
        "deployment_reference": commit,
        "deployment_verified": True,
        "gate_deploy": True,
        "environment": "development",
        "suites": {"playwright": {"tests": [{
            "file": "proof-video-architecture.spec.ts",
            "status": "passed",
            "run_id": "phone-run",
            "artifact_path": str(video),
            "proof_timeline_path": str(timeline),
        }]}},
    }), encoding="utf-8")
    return timeline, run_artifact


def test_playwright_workflow_uses_encoded_phone_content_viewport() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/playwright-spec.yml").read_text(encoding="utf-8")

    assert "PLAYWRIGHT_PROOF_VIDEO_PROFILE: ${{ inputs.proof_video_profile || (inputs.spec == 'proof-video-architecture.spec.ts' && 'web-laptop') || '' }}" in workflow
    assert "inputs.proof_video_profile == 'web-phone' && '390'" in workflow
    assert "inputs.proof_video_profile == 'web-phone' && '630'" in workflow


def test_proof_video_run_directory_uses_control_plane_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tests_control(tmp_path, monkeypatch)

    assert module.proof_video_run_directory(
        session_id="abcd",
        spec_name="example.spec.ts",
        run_id="run-123",
    ) == tmp_path / "test-results" / "proof-videos" / "abcd" / "example.spec-run-123"


def test_initial_welcome_proof_claim_matches_expanded_intro_state() -> None:
    spec = (PROJECT_ROOT / "frontend/apps/web_app/tests/proof-video-architecture.spec.ts").read_text(encoding="utf-8")

    assert "welcome interface is fully visible in the expanded browser welcome card" in spec
    assert "welcome interface is fully visible with its intentional neighboring" not in spec
    assert "Privacy and safety story is visible while the intentional neighboring card preview" in spec


def test_proof_assertions_are_recorded_after_visual_motion_settles() -> None:
    spec = (PROJECT_ROOT / "frontend/apps/web_app/tests/proof-video-architecture.spec.ts").read_text(encoding="utf-8")

    assert spec.index("await waitForFiniteVisualMotion(page, 'landing-intro-expanded');") < spec.index("await proof.assert('welcome.shell.visible'")
    assert spec.index("await waitForFiniteVisualMotion(page, 'guest-slide-content');") < spec.index("await proof.assert('welcome.actionable.visible'")
    privacy_wait = spec.index("await waitForFiniteVisualMotion(page, 'guest-slide-content');", spec.index("open-privacy-story"))
    assert privacy_wait < spec.index("await proof.assert('welcome.privacy.visible'")


def test_playwright_config_uses_phone_profile_for_mobile_touch_viewport(tmp_path: Path) -> None:
    config_url = (PROJECT_ROOT / "frontend/apps/web_app/playwright.config.ts").as_uri()
    loader = tmp_path / "load-playwright-config.mjs"
    loader.write_text(
        f"const config = (await import('{config_url}')).default;\n"
        "console.log(JSON.stringify({ viewport: config.use.viewport ?? null, video: config.use.video, isMobile: config.use.isMobile ?? false, hasTouch: config.use.hasTouch ?? false, colorScheme: config.use.colorScheme ?? null }));\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({
        "PLAYWRIGHT_TEST_BASE_URL": "https://example.invalid",
        "PLAYWRIGHT_PROOF_VIDEO_PROFILE": "web-phone",
        "PLAYWRIGHT_VIDEO_WIDTH": "390",
        "PLAYWRIGHT_VIDEO_HEIGHT": "630",
    })

    result = subprocess.run(
        ["node", "--experimental-strip-types", str(loader)],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(result.stdout)

    assert loaded["viewport"] == {"width": 390, "height": 630}
    assert loaded["video"]["size"] == {"width": 390, "height": 630}
    assert loaded["isMobile"] is True
    assert loaded["hasTouch"] is True
    assert loaded["colorScheme"] == "dark"


def test_playwright_config_keeps_laptop_proof_in_light_mode(tmp_path: Path) -> None:
    config_url = (PROJECT_ROOT / "frontend/apps/web_app/playwright.config.ts").as_uri()
    loader = tmp_path / "load-playwright-laptop-config.mjs"
    loader.write_text(
        f"const config = (await import('{config_url}')).default;\n"
        "console.log(JSON.stringify({ colorScheme: config.use.colorScheme ?? null, isMobile: config.use.isMobile ?? false }));\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({
        "PLAYWRIGHT_TEST_BASE_URL": "https://example.invalid",
        "PLAYWRIGHT_PROOF_VIDEO_PROFILE": "web-laptop",
        "PLAYWRIGHT_VIDEO_WIDTH": "1440",
        "PLAYWRIGHT_VIDEO_HEIGHT": "900",
    })

    result = subprocess.run(
        ["node", "--experimental-strip-types", str(loader)],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(result.stdout)

    assert loaded == {"colorScheme": "light", "isMobile": False}


def test_spec_demo_phone_source_and_final_safari_dimensions() -> None:
    module = load_module(SPEC_DEMO_PATH, "openmates_phone_proof_spec_demo_dimensions")
    profile = module.resolve_device_profile("web-phone")

    module.assert_source_device_profile_dimensions({"width": 390, "height": 630}, profile)
    module.assert_device_profile_dimensions({"width": 390, "height": 844}, profile)
    with pytest.raises(module.DemonstrationError, match="390x630"):
        module.assert_source_device_profile_dimensions({"width": 390, "height": 844}, profile)


def test_proof_source_attestation_persists_phone_profile_from_timeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40
    video = tmp_path / "phone-source.webm"
    video.write_bytes(b"video")
    write_phone_timeline(module, tmp_path, commit=commit, video=video)

    run_data = module.read_json(module.RESULTS_DIR / "last-run.json", {})
    records = module.record_proof_source_attestations(run_data)

    assert len(records) == 1
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    assert payload["proof_video_profile"] == "web-phone"


def test_auto_finalize_web_phone_uses_safari_content_viewport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40
    video = tmp_path / "phone-source.webm"
    video.write_bytes(b"video")
    write_phone_timeline(module, tmp_path, commit=commit, video=video)
    records = module.record_proof_source_attestations(module.read_json(module.RESULTS_DIR / "last-run.json", {}))
    calls: dict[str, object] = {}

    def produce(**kwargs):
        calls["produce"] = kwargs
        return {"spec_id": kwargs["spec_id"], "subject_commit": kwargs["subject_commit"], "publication": {"status": "pending"}}

    finalizations = module.auto_finalize_proof_video_sources(
        {"git_sha": commit, "run_id": "parent-run", "environment": "development"},
        records,
        session_id="8f7c",
        produce_hook=produce,
        review_hook=lambda **_kwargs: {"status": "passed", "manifest": {"review": {"status": "passed"}, "publication": {"status": "pending"}}},
        publish_hook=lambda _run_dir, manifest: {**manifest, "publication": {"status": "delivered", "snippet_html": "<video></video>"}},
        source_duration_hook=lambda _path: 40.0,
    )

    assert finalizations[0]["device_profile"] == "web-phone"
    request = calls["produce"]["browser_tutorial_plan"]["request"]
    assert request["viewport"] == {"width": 390, "height": 630}
    assert request["output"] == {"width": 390, "height": 844, "fps": 30}
    assert request["browserChrome"]["kind"] == "iphone13-pro-safari"
    assert request["browserChrome"]["tabGroupLabel"] == "Personal"
