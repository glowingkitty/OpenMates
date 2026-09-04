#!/usr/bin/env python3
"""Tests for pass-only Apple proof-source finalization.

Synthetic timelines and media placeholders prove native sources reuse the shared
renderer, bounded reviewer, and publication path without requiring Apple hardware.
"""

# contract-test-file: infrastructure

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_control(tmp_path: Path, monkeypatch):
    spec = importlib.util.spec_from_file_location("apple_tests_control", ROOT / "scripts/tests.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    results = tmp_path / "test-results"
    monkeypatch.setattr(module, "RESULTS_DIR", results)
    monkeypatch.setattr(module, "PROOF_SOURCE_DIR", results / "proof-video-sources")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    return module


def make_apple_source(tmp_path: Path, control, profile: str = "apple-iphone-portrait"):
    run_dir = tmp_path / "apple-run"
    run_dir.mkdir()
    (run_dir / "raw.mov").write_bytes(b"video")
    (run_dir / "result.xcresult").mkdir()
    timeline = run_dir / "proof-timeline.json"
    timeline.write_text(json.dumps({
        "schema_version": 1,
        "device": profile,
        "contract": {
            "id": "apple-core-parity",
            "surface": "apple",
            "devices": [profile],
            "transcript": [{"id": "ready", "text": "The Apple chat is ready.", "checkpoint": "ready", "devices": [profile]}],
            "assertions": [{"id": "chat.ready", "visual": "The decrypted chat is visible.", "checkpoint": "ready", "devices": [profile]}],
        },
        "events": [{"kind": "checkpoint", "id": "ready", "at_ms": 100}],
        "assertion_results": [{"id": "chat.ready", "status": "passed", "at_ms": 150}],
    }), encoding="utf-8")
    manifest = {
        "run_id": "apple-run",
        "status": "passed",
        "xcode_exit_code": 0,
        "profile": profile,
        "subject_commit": "a" * 40,
        "test_account_provenance": "reserved Apple E2E account",
        "raw_video": "raw.mov",
        "result_bundle": "result.xcresult",
        "proof_timeline": "proof-timeline.json",
    }
    record = control.record_apple_proof_source_attestation(run_dir, manifest)
    return record


def test_apple_attestation_requires_exact_profile_and_timeline(tmp_path: Path, monkeypatch) -> None:
    control = load_control(tmp_path, monkeypatch)
    record = make_apple_source(tmp_path, control)
    payload = json.loads(record.read_text(encoding="utf-8"))

    assert payload["source_kind"] == "apple"
    assert payload["proof_video_profile"] == "apple-iphone-portrait"
    assert payload["git_sha"] == "a" * 40
    assert payload["raw_artifact_path"].endswith("raw.mov")
    assert payload["raw_artifact_sha256"]


def test_apple_source_reuses_render_review_and_publish(tmp_path: Path, monkeypatch) -> None:
    control = load_control(tmp_path, monkeypatch)
    record = make_apple_source(tmp_path, control)
    calls = {}

    def produce(**kwargs):
        calls["produce"] = kwargs
        return {"publication": {"status": "pending"}}

    def review(**kwargs):
        calls["review"] = kwargs
        return {"status": "passed", "manifest": {"publication": {"status": "pending"}}}

    def publish(run_dir, manifest):
        calls["publish"] = run_dir
        return {**manifest, "publication": {"status": "delivered", "snippet_html": "<video></video>"}}

    result = control.auto_finalize_proof_video_sources(
        {"git_sha": "a" * 40, "run_id": "apple-run", "environment": "apple-simulator"},
        [record],
        session_id="2172",
        produce_hook=produce,
        review_hook=review,
        publish_hook=publish,
        source_duration_hook=lambda _path: 5.0,
    )

    assert result[0]["status"] == "delivered"
    assert calls["produce"]["source"]["kind"] == "apple"
    assert "browser_domain" not in calls["produce"]["source"]
    assert calls["produce"]["device_profile_name"] == "apple-iphone-portrait"
