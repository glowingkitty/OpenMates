# contract-test-file: tooling
"""Exercise framework copy/signing policy without native builds or app launches."""
import importlib.util
from pathlib import Path
import shutil
import sys

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location("embed_onnx_macos", HERE / "embed_onnx_macos.py")
embedding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(embedding)


def fixture_environment(root):
    source = root / "products/onnxruntime.framework"
    binary = source / "Versions/A/onnxruntime"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"normalized dylib")
    (source / "Versions/Current").symlink_to("A")
    (source / "onnxruntime").symlink_to("Versions/Current/onnxruntime")
    return {"PLATFORM_NAME": "macosx", "BUILT_PRODUCTS_DIR": str(root / "products"),
            "TARGET_BUILD_DIR": str(root / "target"),
            "FRAMEWORKS_FOLDER_PATH": "OpenMates.app/Contents/Frameworks"}


@pytest.mark.parametrize("allowed,identity", [("NO", None), ("YES", "TEAM-CERT"), ("YES", "")])
def test_embed_preserves_symlinks_binary_and_input_and_signs_only_copy(tmp_path, monkeypatch, allowed, identity):
    environment = fixture_environment(tmp_path)
    environment["CODE_SIGNING_ALLOWED"] = allowed
    if identity is not None:
        environment["EXPANDED_CODE_SIGN_IDENTITY"] = identity
    source, destination = embedding.scoped_paths(environment, tmp_path)
    calls = []
    verified = []
    monkeypatch.setattr(embedding, "verify_dynamic", lambda binary: verified.append(binary))
    def run(command):
        calls.append(command)
        if command[0] == "ditto":
            shutil.copytree(command[1], command[2], symlinks=True, dirs_exist_ok=True)
        return ""
    monkeypatch.setattr(embedding, "run", run)
    result = embedding.embed(environment, tmp_path)
    assert (destination / "onnxruntime").is_symlink()
    assert (destination / "Versions/Current").readlink() == Path("A")
    assert (destination / "onnxruntime").read_bytes() == b"normalized dylib"
    assert result["source_binary_sha256"] == result["embedded_binary_sha256"]
    assert result["signed"] == (allowed == "YES")
    signing = [command for command in calls if "--sign" in command]
    assert len(signing) == (1 if allowed == "YES" else 0)
    if signing:
        assert signing[0][signing[0].index("--sign") + 1] == (identity or "-")
        assert signing[0][-1] == str(destination)
        assert any("--verify" in command for command in calls)
    assert source / "Versions/A/onnxruntime" in verified
    assert destination / "Versions/A/onnxruntime" in verified


def test_ios_skips_without_build_paths():
    assert embedding.embed({"PLATFORM_NAME": "iphoneos"}) is None
    assert embedding.embed({"PLATFORM_NAME": "iphonesimulator"}) is None


def test_shared_embedding_phase_does_not_claim_swiftpm_ios_output():
    import yaml

    project = yaml.safe_load((HERE.parent / "project.yml").read_text())
    phase = next(
        item for item in project["targets"]["OpenMates"]["postBuildScripts"]
        if item["name"] == "Embed macOS ONNX Runtime"
    )
    assert phase["basedOnDependencyAnalysis"] is False
    assert not phase.get("outputFiles")


@pytest.mark.parametrize("folder", ["../../outside", "/outside", ""])
def test_destination_must_be_owned_target_path(tmp_path, folder):
    environment = fixture_environment(tmp_path)
    environment["FRAMEWORKS_FOLDER_PATH"] = folder
    with pytest.raises(ValueError):
        embedding.scoped_paths(environment, tmp_path)


def test_source_package_artifact_is_rejected(tmp_path):
    environment = fixture_environment(tmp_path)
    environment["BUILT_PRODUCTS_DIR"] = str(tmp_path / "SourcePackages/artifacts")
    with pytest.raises(ValueError, match="isolated repository"):
        embedding.scoped_paths(environment, tmp_path)


def test_static_source_is_rejected_before_copy(tmp_path, monkeypatch):
    environment = fixture_environment(tmp_path)
    def reject(binary):
        raise ValueError("ONNX runtime is not a dynamic library")
    monkeypatch.setattr(embedding, "verify_dynamic", reject)
    monkeypatch.setattr(embedding, "run", lambda command: pytest.fail("copy must not run"))
    with pytest.raises(ValueError, match="dynamic library"):
        embedding.embed(environment, tmp_path)


def test_corrupt_copy_is_rejected(tmp_path, monkeypatch):
    environment = fixture_environment(tmp_path)
    monkeypatch.setattr(embedding, "verify_dynamic", lambda binary: None)
    def corrupt(command):
        destination = Path(command[-1]) / "Versions/A/onnxruntime"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"corrupt")
    monkeypatch.setattr(embedding, "run", corrupt)
    with pytest.raises(ValueError, match="verified input"):
        embedding.embed(environment, tmp_path)


def test_existing_destination_cannot_redirect_copy_outside_framework(tmp_path):
    environment = fixture_environment(tmp_path)
    _, destination = embedding.scoped_paths(environment, tmp_path)
    (destination / "Versions").mkdir(parents=True)
    (destination / "Versions/A").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        embedding.scoped_paths(environment, tmp_path)
