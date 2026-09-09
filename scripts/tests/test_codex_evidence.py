"""Visual delivery regressions with isolated synthetic recording attachments.

Cover multiple specs, retries, profiles, missing capture and expiring uploads.
No real S3 request or test rerun is made. The existing transport is injected.
Test success must remain independent from media delivery success.
See docs/architecture/codex-orchestration.md.
"""

# contract-test-file: tooling
import json
from scripts import codex_evidence as media


def receipt():
    return {
        "source_commit": "abc",
        "run_id": 9,
        "report": {"results": [{"spec": "chat.spec.ts"}]},
    }


def fixture(tmp_path):
    specs = []
    for index, profile in enumerate(("phone", "laptop")):
        results = []
        for retry in (0, 1):
            video = f"{index}-{retry}.mp4"
            (tmp_path / video).write_bytes(b"fixture")
            results.append(
                {
                    "retry": retry,
                    "status": "failed" if retry == 0 else "passed",
                    "attachments": [{"path": video}],
                }
            )
        specs.append(
            {
                "file": "chat.spec.ts",
                "id": str(index),
                "tests": [{"projectName": profile, "results": results}],
            }
        )
    (tmp_path / "ci-spec-0.json").write_text(json.dumps({"suites": [{"specs": specs}]}))
    return media.prepare(tmp_path, receipt())


def test_all_attempts_profiles_survive_and_uploads_are_cached(tmp_path):
    path = fixture(tmp_path)
    calls = []

    def upload(file, **kw):
        calls.append(file)
        return {
            "url": "https://bucket.example.test/file?signature=test",
            "expires_in": 172800,
        }

    media.publish(tmp_path, upload, now=100)
    state = media.publish(tmp_path, upload, now=101)
    assert len(calls) == 4 and len(state["records"]) == 4
    assert all(r["delivery"] == "pending" for r in state["records"].values())
    media.prepare(tmp_path, receipt())
    assert all(
        r["upload"] == "uploaded"
        for r in json.loads(path.read_text())["records"].values()
    )
    media.publish(tmp_path, upload, now=200000)
    assert len(calls) == 8


def test_missing_early_capture_is_explicit(tmp_path):
    path = media.prepare(tmp_path, receipt())
    row = next(iter(json.loads(path.read_text())["records"].values()))
    assert row["recording"] == "unavailable" and "No attempt report" in row["reason"]


def test_upload_failure_preserves_test_result_and_retry_is_artifact_only(tmp_path):
    fixture(tmp_path)

    def fail(*a, **k):
        raise RuntimeError("unavailable")

    state = media.publish(tmp_path, fail, now=1)
    assert all(r["upload"] == "failed" for r in state["records"].values())
    assert {r["result"] for r in state["records"].values()} == {"passed", "failed"}


def test_ambiguous_or_private_paths_are_not_selected(tmp_path):
    import pytest

    for dirname in ("one", "two"):
        path = tmp_path / dirname
        path.mkdir()
        (path / "video.mp4").write_bytes(b"fixture")
    with pytest.raises(ValueError):
        media.resolve_attachment(tmp_path, "/runner/video.mp4")
    with pytest.raises(ValueError):
        media.resolve_attachment(tmp_path, "../video.mp4")


def test_setup_failure_retains_each_selected_spec_obligation(tmp_path):
    data = {
        "source_commit": "abc",
        "run_id": 9,
        "report": None,
        "selected_specs": ["one.spec.ts", "two.spec.ts"],
    }
    records = media.collect(tmp_path, data)
    assert {r["spec"] for r in records} == {"one.spec.ts", "two.spec.ts"}
    assert all(r["recording"] == "unavailable" for r in records)


def test_cli_product_recording_included_but_generic_script_excluded(tmp_path):
    from scripts.cli_video_capture import build_capture_manifest

    (tmp_path / "cli.mp4").write_bytes(b"cli")
    (tmp_path / "transcript.txt").write_text("synthetic CLI output")
    (tmp_path / "events.jsonl").write_text("")
    manifest = build_capture_manifest(
        argv=["openmates", "chats", "list"],
        video_path=tmp_path / "cli.mp4",
        transcript_path=tmp_path / "transcript.txt",
        events_path=tmp_path / "events.jsonl",
        exit_status=1,
        target_environment="github-isolated",
        classification="cli_e2e",
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    records = media.collect(tmp_path, receipt())
    assert any(
        r.get("profile") == "terminal"
        and r["result"] == "failed"
        and r["recording"] == "available"
        for r in records
    )
    (tmp_path / "cli.mp4").write_bytes(b"changed")
    assert any(
        r.get("profile") == "terminal" and r["recording"] == "unavailable"
        for r in media.collect(tmp_path, receipt())
    )
    manifest["argv"] = ["python3", "generic.py"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not any(
        r.get("profile") == "terminal" for r in media.collect(tmp_path, receipt())
    )
