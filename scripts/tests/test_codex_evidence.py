"""Visual delivery regressions with isolated synthetic recording attachments.

Cover multiple specs, retries, profiles, missing capture and expiring uploads.
No real S3 request or test rerun is made. The existing transport is injected.
Test success must remain independent from media delivery success.
See docs/architecture/codex-orchestration.md.
"""

# contract-test-file: tooling
import json
import hashlib
import pytest
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


def uploaded_response(file, expires_in=172800):
    return {
        "url": "https://bucket.example.test/file", "expires_in": expires_in,
        "bucket": "dev-openmates-opencode-response-media", "key": "review-responses/file",
        "sha256": "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest(),
    }


def test_all_attempts_profiles_survive_and_uploads_are_cached(tmp_path):
    path = fixture(tmp_path)
    calls = []

    def upload(file, **kw):
        calls.append(file)
        return {
            "url": "https://bucket.example.test/file?signature=test",
            "expires_in": 172800,
            "bucket": "dev-openmates-opencode-response-media",
            "key": "review-responses/runs/fixture/video.mp4",
            "sha256": "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest(),
        }

    media.publish(tmp_path, upload, now=100)
    state = media.publish(tmp_path, upload, now=101)
    assert len(calls) == 4 and len(state["records"]) == 4
    assert not any(tmp_path.glob("*.mp4"))
    assert all(r["local_video_removed"] for r in state["records"].values())
    assert all(r["delivery"] == "pending" for r in state["records"].values())
    media.prepare(tmp_path, receipt())
    assert len(json.loads(path.read_text())["records"]) == 4
    assert all(
        r["upload"] == "uploaded"
        for r in json.loads(path.read_text())["records"].values()
    )
    renewed = []
    def renewer(**kw):
        renewed.append(kw)
        return {**kw, "sha256": "sha256:" + kw["sha256"],
                "url": "https://bucket.example.test/renewed?signature=test", "expires_in": 172800}
    media.publish(tmp_path, upload, now=200000, renewer=renewer)
    assert len(calls) == 4 and len(renewed) == 4


def test_other_source_commit_does_not_reuse_uploaded_record(tmp_path):
    path = fixture(tmp_path)
    media.publish(tmp_path, lambda file, **kw: uploaded_response(file), now=1)
    other_revision = {**receipt(), "source_commit": "different-revision"}
    media.prepare(tmp_path, other_revision)
    records = list(json.loads(path.read_text())["records"].values())
    missing = [r for r in records if r["source_commit"] == "different-revision"]
    assert len(missing) == 4
    assert all(r["recording"] == "unavailable" for r in missing)
    assert all(r["source_commit"] == "abc" and r["upload"] == "uploaded"
               for r in records if r not in missing)


def test_shared_video_uploads_for_each_record_before_cleanup(tmp_path):
    video = tmp_path / "shared.mp4"
    video.write_bytes(b"shared proof")
    specs = [{
        "file": "chat.spec.ts", "id": str(index),
        "tests": [{"projectName": "laptop", "results": [{
            "retry": 0, "status": "passed", "attachments": [{"path": "shared.mp4"}],
        }]}],
    } for index in range(2)]
    (tmp_path / "ci-spec-shared.json").write_text(json.dumps({"suites": [{"specs": specs}]}))
    path = media.prepare(tmp_path, receipt())
    uploaded = []
    def upload(file, **kw):
        assert file == video and video.exists()
        uploaded.append(file)
        return uploaded_response(file)
    state = media.publish(tmp_path, upload, now=1)
    assert len(uploaded) == 2
    assert not video.exists()
    assert all(r["upload"] == "uploaded" and r["local_video_removed"]
               for r in state["records"].values())
    media.prepare(tmp_path, receipt())
    assert len(json.loads(path.read_text())["records"]) == 2


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
    assert len(list(tmp_path.glob("*.mp4"))) == 4
    assert {r["result"] for r in state["records"].values()} == {"passed", "failed"}


def test_crash_after_receipt_save_resumes_cleanup(tmp_path, monkeypatch):
    fixture(tmp_path)
    def upload(file, **kw):
        return uploaded_response(file)
    original = media._cleanup_uploaded_videos
    monkeypatch.setattr(media, "_cleanup_uploaded_videos", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        media.publish(tmp_path, upload, now=1)
    assert len(list(tmp_path.glob("*.mp4"))) == 4
    assert all(r["bucket"] for r in json.loads((tmp_path / "codex-evidence.json").read_text())["records"].values())
    monkeypatch.setattr(media, "_cleanup_uploaded_videos", original)
    state = media.publish(tmp_path, upload, now=2)
    assert len(list(tmp_path.glob("*.mp4"))) == 0
    assert all(r["local_video_removed"] for r in state["records"].values())


def test_crash_after_unlink_before_cleanup_save_recovers(tmp_path, monkeypatch):
    fixture(tmp_path)
    def upload(file, **kw):
        return uploaded_response(file)
    media.publish(tmp_path, upload, now=1, retain_local_videos=True)
    original = type(tmp_path).unlink
    crashed = False
    def unlink_then_crash(self, *args, **kwargs):
        nonlocal crashed
        original(self, *args, **kwargs)
        if not crashed:
            crashed = True
            raise RuntimeError("crash after unlink")
    monkeypatch.setattr(type(tmp_path), "unlink", unlink_then_crash)
    with pytest.raises(RuntimeError, match="crash after unlink"):
        media.publish(tmp_path, upload, now=2)
    monkeypatch.setattr(type(tmp_path), "unlink", original)
    state = media.publish(tmp_path, upload, now=3)
    assert all(r["local_video_removed"] for r in state["records"].values())
    assert not list(tmp_path.glob("*.mp4"))


def test_expired_remote_object_does_not_fake_renewal_or_reupload(tmp_path):
    fixture(tmp_path)
    def upload(file, **kw):
        return uploaded_response(file, expires_in=100)
    media.publish(tmp_path, upload, now=1)
    def expired(**kw):
        raise RuntimeError("object expired")
    state = media.publish(tmp_path, lambda *a, **kw: pytest.fail("must not reupload"), now=200, renewer=expired)
    assert all(r["upload"] == "uploaded" and r["link_expired"] for r in state["records"].values())
    assert "Remote evidence unavailable or expired" in media.markdown(state)
    assert "https://bucket.example.test/file" not in media.markdown(state)


def test_renewal_cannot_replace_saved_remote_identity(tmp_path):
    fixture(tmp_path)
    media.publish(tmp_path, lambda file, **kw: uploaded_response(file, expires_in=100), now=1)
    def switched(**kw):
        return {**kw, "key": "review-responses/other", "sha256": "sha256:" + kw["sha256"],
                "url": "https://bucket.example.test/other", "expires_in": 172800}
    state = media.publish(tmp_path, lambda *a, **kw: pytest.fail("must not reupload"), now=200, renewer=switched)
    assert all(r["key"] == "review-responses/file" and r["link_expired"] for r in state["records"].values())


def test_cleanup_preserves_changed_video_and_requested_edit(tmp_path):
    fixture(tmp_path)
    def upload(file, **kw):
        return uploaded_response(file)
    media.publish(tmp_path, upload, now=1, retain_local_videos=True)
    assert len(list(tmp_path.glob("*.mp4"))) == 4
    (tmp_path / "0-0.mp4").write_bytes(b"changed")
    state = media.publish(tmp_path, upload, now=2)
    assert (tmp_path / "0-0.mp4").exists()
    assert any(r.get("cleanup_error") == "ValueError" for r in state["records"].values())
    assert len(list(tmp_path.glob("*.mp4"))) == 1


def test_cleanup_refuses_symlink(tmp_path):
    fixture(tmp_path)
    outside = tmp_path.parent / "outside-evidence.mp4"
    outside.write_bytes(b"fixture")
    (tmp_path / "0-0.mp4").unlink()
    (tmp_path / "0-0.mp4").symlink_to(outside)
    def upload(file, **kw):
        return {"url": "https://bucket.example.test/file", "expires_in": 172800,
                "bucket": "dev-openmates-opencode-response-media", "key": "review-responses/file",
                "sha256": "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()}
    state = media.publish(tmp_path, upload, now=1)
    assert (tmp_path / "0-0.mp4").is_symlink() and outside.exists()
    assert sum(r["upload"] == "failed" for r in state["records"].values()) == 1
    assert all(r.get("local_video_removed") for r in state["records"].values() if r["upload"] == "uploaded")


def test_unconfirmed_remote_identity_retains_video(tmp_path):
    fixture(tmp_path)
    def upload(file, **kw):
        return {**uploaded_response(file), "sha256": "sha256:" + "0" * 64}
    state = media.publish(tmp_path, upload, now=1)
    assert all(r["upload"] == "failed" for r in state["records"].values())
    assert len(list(tmp_path.glob("*.mp4"))) == 4


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


def test_cli_uploaded_recording_does_not_gain_missing_row_after_cleanup(tmp_path):
    from scripts.cli_video_capture import build_capture_manifest

    video = tmp_path / "cli.mp4"
    video.write_bytes(b"cli")
    (tmp_path / "transcript.txt").write_text("synthetic CLI output")
    (tmp_path / "events.jsonl").write_text("")
    manifest = build_capture_manifest(
        argv=["openmates", "chats", "list"], video_path=video,
        transcript_path=tmp_path / "transcript.txt",
        events_path=tmp_path / "events.jsonl", exit_status=0,
        target_environment="github-isolated", classification="cli_e2e",
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    state_path = media.prepare(tmp_path, receipt())
    media.publish(tmp_path, lambda file, **kw: uploaded_response(file), now=1)
    assert not video.exists()
    media.prepare(tmp_path, receipt())
    records = json.loads(state_path.read_text())["records"]
    cli_records = [record for record in records.values() if record.get("profile") == "terminal"]
    assert len(cli_records) == 1
    assert cli_records[0]["upload"] == "uploaded"
