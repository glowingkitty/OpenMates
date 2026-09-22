from __future__ import annotations

# contract-test-file: tooling

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
release = importlib.import_module("publish_stable_github_release")


def test_release_identity_requires_matching_stable_versions(tmp_path: Path) -> None:
    config = tmp_path / "product_version.json"
    config.write_text(
        json.dumps(
            {
                "userFacing": "v0.19",
                "cli": {"stableBase": "0.19.0"},
                "python": {"stableBase": "0.19.0"},
            }
        ),
        encoding="utf-8",
    )

    identity = release.load_release_identity(config)

    assert identity.version == "0.19.0"
    assert identity.tag == "v0.19.0"


def test_release_identity_rejects_split_package_versions(tmp_path: Path) -> None:
    config = tmp_path / "product_version.json"
    config.write_text(
        json.dumps(
            {
                "userFacing": "v0.19",
                "cli": {"stableBase": "0.19.0"},
                "python": {"stableBase": "0.18.0"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(release.StableReleaseError, match="differ"):
        release.load_release_identity(config)


def test_workflow_gate_uses_latest_same_commit_push_runs() -> None:
    commit = "a" * 40
    payload = {
        "workflow_runs": [
            {
                "id": 1,
                "name": "Publish CLI",
                "head_sha": commit,
                "event": "push",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "id": 2,
                "name": "Publish CLI",
                "head_sha": commit,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 3,
                "name": "Publish Python SDK",
                "head_sha": commit,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 4,
                "name": "Publish Self-Host Images",
                "head_sha": commit,
                "event": "push",
                "status": "in_progress",
                "conclusion": None,
            },
            {
                "id": 99,
                "name": "Publish Self-Host Images",
                "head_sha": "b" * 40,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    }

    assert release.latest_required_workflow_states(payload, commit) == {
        "Publish CLI": ("completed", "success"),
        "Publish Python SDK": ("completed", "success"),
        "Publish Self-Host Images": ("in_progress", ""),
    }


def test_release_notes_pin_all_installation_versions() -> None:
    identity = release.ReleaseIdentity("0.19.0", "v0.19.0", "v0.19")

    notes = release.release_notes(identity, "c" * 40)

    assert "openmates@0.19.0" in notes
    assert "openmates==0.19.0" in notes
    assert "server update --channel stable" in notes
    assert "c" * 40 in notes


def test_image_verification_compares_version_and_commit_manifests(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = release.ReleaseIdentity("0.19.0", "v0.19.0", "v0.19")
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='{"digest":"same"}', stderr="")

    monkeypatch.setattr(release, "STABLE_IMAGES", ("openmates-api",))
    monkeypatch.setattr(release, "run", fake_run)

    release.verify_versioned_images(identity, "d" * 40)

    assert commands == [
        [
            "docker", "buildx", "imagetools", "inspect", "--raw",
            "ghcr.io/glowingkitty/openmates-api:v0.19.0",
        ],
        [
            "docker", "buildx", "imagetools", "inspect", "--raw",
            f"ghcr.io/glowingkitty/openmates-api:sha-{'d' * 40}",
        ],
    ]


def test_image_verification_rejects_mismatched_commit_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = release.ReleaseIdentity("0.19.0", "v0.19.0", "v0.19")
    outputs = iter(("versioned", "immutable"))

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(release, "STABLE_IMAGES", ("openmates-api",))
    monkeypatch.setattr(release, "run", fake_run)

    with pytest.raises(release.StableReleaseError, match="does not match release commit"):
        release.verify_versioned_images(identity, "d" * 40)


def test_existing_annotated_tag_is_resolved_to_release_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = release.ReleaseIdentity("0.19.0", "v0.19.0", "v0.19")
    commit = "e" * 40
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if "/git/ref/tags/" in command[2]:
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps({"object": {"type": "tag", "sha": "tag-object"}}), stderr=""
            )
        return subprocess.CompletedProcess(command, 0, stdout=commit, stderr="")

    monkeypatch.setattr(release, "run", fake_run)

    release.ensure_annotated_tag("glowingkitty/OpenMates", identity, commit)

    assert len(commands) == 2
    assert commands[1][2].endswith("/git/tags/tag-object")


def test_release_workflow_waits_for_all_artifact_publishers() -> None:
    workflow = (ROOT / ".github/workflows/publish-github-release.yml").read_text(encoding="utf-8")

    for name in release.REQUIRED_WORKFLOWS:
        assert f"- {name}" in workflow
    assert "head_branch == 'main'" in workflow
    assert "head_sha || inputs.commit" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "--apply" in workflow
