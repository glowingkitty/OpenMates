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


def test_preprovisioned_recording_uses_marker_without_rewriting_credentials() -> None:
    module = load_module()
    command = module.recorded_test_ios_command(
        simulator="iPhone 15 Pro",
        only_testing="OpenMatesUITests/ChatFlowRealAccountUITests/testAppleCoreParityProof",
        profile="apple-iphone-portrait",
        run_id="apple-proof-2",
        expected_commit="a" * 40,
        test_account_env={"OPENMATES_APPLE_PROOF_ACCOUNT_SLOT": "14"},
        proof=True,
        preprovisioned_credentials=True,
    )

    assert "OPENMATES_APPLE_PROOF_ACCOUNT_SLOT=14" in command
    assert "lines.append(f\"{key}=" not in command
    assert "unlink(missing_ok=True)" in command


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
    monkeypatch.setattr(module, "reserved_test_account_env", lambda _slot: {
        "OPENMATES_TEST_ACCOUNT_14_EMAIL": "reserved@example.test",
        "OPENMATES_TEST_ACCOUNT_14_PASSWORD": "password",
        "OPENMATES_TEST_ACCOUNT_14_OTP_KEY": "otp-key",
        "OPENMATES_APPLE_PROOF_ACCOUNT_SLOT": "14",
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
            github_secret_broker=False,
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
            github_secret_broker=False,
            runner=lambda _command: pytest.fail("remote runner must not execute"),
        )


def test_reserved_slot_materializes_only_requested_expanded_account() -> None:
    module = load_module()
    values = module.reserved_test_account_env(14, {
        "OPENMATES_TEST_ACCOUNT_EMAIL": "generic@example.test",
        "OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON": json.dumps({
            "14": {"email": "reserved@example.test", "password": "password", "otpKey": "otp-key"},
            "15": {"email": "other@example.test", "password": "other", "otpKey": "other-key"},
        }),
    })

    assert values == {
        "OPENMATES_TEST_ACCOUNT_14_EMAIL": "reserved@example.test",
        "OPENMATES_TEST_ACCOUNT_14_PASSWORD": "password",
        "OPENMATES_TEST_ACCOUNT_14_OTP_KEY": "otp-key",
        "OPENMATES_APPLE_PROOF_ACCOUNT_SLOT": "14",
    }


def test_credential_broker_workflow_has_no_direct_mac_transport() -> None:
    workflow = (ROOT / ".github/workflows/apple-proof-credential-broker.yml").read_text(encoding="utf-8")

    assert "actions/upload-artifact@v4" in workflow
    assert "credentials.cms" in workflow
    assert "credentials.env" not in workflow
    assert "retention-days: 1" in workflow
    assert "ssh" not in workflow.lower()
    assert "scp" not in workflow.lower()
    assert "tailscale" not in workflow.lower()
    assert "apple_remote.py" not in workflow
    assert "recipient-key" not in workflow
    assert "credential_path.unlink(missing_ok=True)" in module_source("scripts/apple_remote.py")


def module_source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_proof_broker_recipient_returns_only_public_certificate() -> None:
    module = load_module()
    certificate = b"-----BEGIN CERTIFICATE-----\npublic\n-----END CERTIFICATE-----\n"

    def runner(_command):
        encoded = module.base64.b64encode(certificate).decode("ascii")
        return subprocess.CompletedProcess([], 0, f"proof_broker_recipient_certificate_b64={encoded}\n", "")

    result = module.proof_broker_recipient_certificate(
        module.RemoteConfig(target="macos-peer", repo_path="/repo", source="test"),
        runner=runner,
    )

    assert result == certificate


def test_relay_identity_rejects_non_committed_public_key(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    root = tmp_path / "relay"
    private_key = root / "relay-key.pem"
    public_key = root / "relay-public.pem"
    committed = tmp_path / "committed-public.pem"
    root.mkdir()
    private_key.write_bytes(b"private")
    committed.write_bytes(b"expected-public")
    monkeypatch.setattr(module, "APPLE_PROOF_BROKER_LOCAL_ROOT", root)
    monkeypatch.setattr(module, "APPLE_PROOF_BROKER_RELAY_KEY", private_key)
    monkeypatch.setattr(module, "APPLE_PROOF_BROKER_RELAY_PUBLIC_KEY", public_key)
    monkeypatch.setattr(module, "APPLE_PROOF_BROKER_COMMITTED_RELAY_PUBLIC_KEY", committed)

    def runner(command):
        if command[:2] == ["openssl", "pkey"]:
            public_key.write_bytes(b"different-public")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(module.AppleRemoteError, match="committed public key"):
        module.proof_broker_relay_public_key(
            module.RemoteConfig(target="macos-peer", repo_path="/repo", source="configured"),
            runner=runner,
        )


def test_broker_mode_does_not_load_local_credentials(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(
        module,
        "local_test_account_env",
        lambda: pytest.fail("broker mode must not load local credentials"),
    )
    monkeypatch.setattr(module, "provision_github_proof_credentials", lambda *_args, **_kwargs: "request")
    calls = 0

    def runner(command):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1 if calls == 1 else 0, "", "")

    result = module.run_recorded_ios_test(
        module.RemoteConfig(target="macos-peer", repo_path="/repo", source="configured"),
        simulator="iPhone 15 Pro",
        only_testing="OpenMatesUITests/Proof",
        profile="apple-iphone-portrait",
        proof=True,
        expected_commit="a" * 40,
        test_account_slot=14,
        github_secret_broker=True,
        runner=runner,
    )

    assert result == 1


def test_artifact_cleanup_fails_closed_when_github_lookup_fails() -> None:
    module = load_module()

    with pytest.raises(module.AppleRemoteError, match="inspect encrypted"):
        module._delete_github_proof_broker_artifact(
            123,
            "apple-proof-credentials-request",
            runner=lambda command: subprocess.CompletedProcess(command, 1, "", ""),
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
