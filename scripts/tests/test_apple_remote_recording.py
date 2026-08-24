#!/usr/bin/env python3
"""Tests for remote Apple UI-test recording and artifact transfer.

The suite validates command construction and local archive verification only.
It never contacts a Mac, opens credentials, or records private simulator data.
"""

# contract-test-file: infrastructure

import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/apple_remote.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apple_remote_recording", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_recording_command_owns_video_result_bundle_and_cleanup() -> None:
    module = load_module()
    command = module.recorded_test_ios_command(
        simulator="iPhone 17",
        only_testing="OpenMatesUITests/AuthSecurityParityUITests",
        profile="apple-iphone-portrait",
        run_id="apple-proof-1",
        test_account_env={},
        proof=True,
    )

    assert "recordVideo" in command
    assert "-resultBundlePath" in command
    assert "result.xcresult" in command
    assert "xcresulttool" in command
    assert '"console"' in command
    assert "console.log" in command
    assert "live-app.log" in command
    assert "process ==" in command
    assert "OpenMates" in command
    assert "finally:" in command
    assert "recorder.send_signal(signal.SIGINT)" in command
    assert "artifact-manifest.json" in command
    assert "raw.mov" in command
    assert command.endswith(" true")


def test_proof_recording_requires_timeline_before_marking_passed() -> None:
    module = load_module()

    assert "and (not proof or timeline is not None)" in module.RECORDED_IOS_TEST_SCRIPT


def test_recording_parser_accepts_only_exact_apple_profiles() -> None:
    module = load_module()
    parser = module.build_parser()

    args = parser.parse_args(["test-ios", "--record-profile", "apple-ipad-landscape", "--proof"])
    assert args.record_profile == "apple-ipad-landscape"
    assert args.proof is True

    with pytest.raises(SystemExit):
        parser.parse_args(["test-ios", "--record-profile", "web-laptop"])


def test_archive_validation_rejects_path_traversal(tmp_path: Path) -> None:
    module = load_module()
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("../escape")
        payload = b"bad"
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))

    with pytest.raises(module.AppleRemoteError, match="unsafe path"):
        module.extract_and_validate_recording_archive(archive, tmp_path / "out")


def test_archive_validation_checks_manifest_hashes(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "raw.mov").write_bytes(b"video")
    result_bundle = source / "result.xcresult"
    result_bundle.mkdir()
    (result_bundle / "Info.plist").write_bytes(b"result")
    (source / "artifact-manifest.json").write_text(json.dumps({
        "run_id": "run-1",
        "status": "passed",
        "raw_video": "raw.mov",
        "result_bundle": "result.xcresult",
        "artifacts": [
            {"path": "raw.mov", "sha256": "0" * 64},
            {"path": "result.xcresult/Info.plist", "sha256": module.hashlib.sha256(b"result").hexdigest()},
        ],
    }), encoding="utf-8")
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="run-1")

    with pytest.raises(module.AppleRemoteError, match="hash mismatch"):
        module.extract_and_validate_recording_archive(archive, tmp_path / "out")


def test_archive_validation_rejects_undeclared_top_level_artifact_path(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "raw.mov").write_bytes(b"video")
    result_bundle = source / "result.xcresult"
    result_bundle.mkdir()
    (result_bundle / "Info.plist").write_bytes(b"result")
    raw_hash = module.hashlib.sha256(b"video").hexdigest()
    result_hash = module.hashlib.sha256(b"result").hexdigest()
    (source / "artifact-manifest.json").write_text(json.dumps({
        "run_id": "run-1",
        "status": "passed",
        "raw_video": "../outside.mov",
        "result_bundle": "result.xcresult",
        "artifacts": [
            {"path": "raw.mov", "sha256": raw_hash},
            {"path": "result.xcresult/Info.plist", "sha256": result_hash},
        ],
    }), encoding="utf-8")
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="run-1")

    with pytest.raises(module.AppleRemoteError, match="raw_video is not a declared run-local artifact"):
        module.extract_and_validate_recording_archive(archive, tmp_path / "out")


def test_proof_rejects_simulator_that_does_not_match_profile(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(module, "local_test_account_env", lambda: {
        "OPENMATES_TEST_ACCOUNT_14_EMAIL": "reserved@example.test",
        "OPENMATES_TEST_ACCOUNT_14_PASSWORD": "password",
        "OPENMATES_TEST_ACCOUNT_14_OTP_KEY": "otp-key",
    })

    with pytest.raises(module.AppleRemoteError, match="approved simulator"):
        module.run_recorded_ios_test(
            module.RemoteConfig(target="macos-peer", repo_path="/repo", source="test"),
            simulator="iPhone 17",
            only_testing="OpenMatesUITests/Proof",
            profile="apple-iphone-portrait",
            proof=True,
            expected_commit="a" * 40,
            test_account_slot=14,
            runner=lambda _command: pytest.fail("remote runner must not execute"),
        )


def test_proof_rejects_generic_or_unreserved_account_slot() -> None:
    module = load_module()

    with pytest.raises(module.AppleRemoteError, match="reserved Apple range 14-20"):
        module.run_recorded_ios_test(
            module.RemoteConfig(target="macos-peer", repo_path="/repo", source="test"),
            simulator="iPhone 15 Pro",
            only_testing="OpenMatesUITests/Proof",
            profile="apple-iphone-portrait",
            proof=True,
            expected_commit="a" * 40,
            test_account_slot=1,
            runner=lambda _command: pytest.fail("remote runner must not execute"),
        )


def test_proof_video_normalization_retains_raw_and_uses_exact_profile(tmp_path: Path) -> None:
    module = load_module()
    raw_video = tmp_path / "raw.mov"
    raw_video.write_bytes(b"raw-retina-video")
    manifest = {"profile": "apple-iphone-portrait", "raw_video": raw_video.name}
    dimensions = {raw_video: (1178, 2556)}
    captured = {}

    def runner(command):
        captured["command"] = command
        output = Path(command[-1])
        output.write_bytes(b"normalized-video")
        dimensions[output] = (393, 852)
        return subprocess.CompletedProcess(command, 0, "", "")

    output = module.normalize_apple_proof_video(
        tmp_path,
        manifest,
        runner=runner,
        dimensions_reader=lambda path: dimensions[path],
    )

    assert raw_video.read_bytes() == b"raw-retina-video"
    assert output.name == "proof-source.mp4"
    assert manifest["proof_video"] == output.name
    assert manifest["raw_video_sha256"] == module.hashlib.sha256(raw_video.read_bytes()).hexdigest()
    assert "scale=393:852:flags=lanczos,setsar=1" in captured["command"]
    assert "yuv444p" in captured["command"]
