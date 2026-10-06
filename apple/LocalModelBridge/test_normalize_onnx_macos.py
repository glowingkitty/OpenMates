# contract-test-file: tooling
"""Packaging contract tests use fake tool output, never build or launch apps."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("normalize_onnx_macos", Path(__file__).with_name("normalize_onnx_macos.py"))
normalizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normalizer)


def fake_tools(monkeypatch, *, private_export=False):
    calls = []

    def run(command):
        calls.append(command)
        if command[0] == "file":
            return "current ar archive" if Path(command[-1]).read_bytes() == b"static" else "Mach-O universal binary"
        if "-archs" in command:
            return "arm64 x86_64"
        if "-hv" in command:
            return "MH_DYLIB"
        if "-D" in command:
            return "binary:\n" + normalizer.INSTALL_NAME
        if "nm" in command:
            return "\n".join(normalizer.EXPORTS | ({"_xnn_initialize"} if private_export else set()))
        if "--show-sdk-path" in command:
            return "/SDK"
        if "clang" in command:
            Path(command[-1]).write_bytes(b"dynamic-slice")
        elif "-create" in command:
            Path(command[-1]).write_bytes(b"dynamic-universal")
        return ""

    monkeypatch.setattr(normalizer, "run", run)
    return calls


def test_normalization_preserves_static_input_and_is_idempotent(tmp_path, monkeypatch):
    binary = tmp_path / "onnxruntime"
    binary.write_bytes(b"static")
    calls = fake_tools(monkeypatch)
    receipt = normalizer.normalize(binary, tmp_path / "state")
    assert Path(receipt["original"]).read_bytes() == b"static"
    assert binary.read_bytes() == b"dynamic-universal"
    assert json.loads((tmp_path / "state/receipt.json").read_text()) == receipt
    clang_calls = [command for command in calls if "clang" in command]
    assert len(clang_calls) == 2
    assert {command[command.index("-target") + 1] for command in clang_calls} == {
        "arm64-apple-macos14.0", "x86_64-apple-macos14.0"}
    assert all("-exported_symbols_list" in command and "-force_load" in command for command in clang_calls)
    assert normalizer.normalize(binary, tmp_path / "state") == receipt
    assert len([command for command in calls if "clang" in command]) == 2


def test_private_exports_reject_candidate_and_keep_original(tmp_path, monkeypatch):
    binary = tmp_path / "onnxruntime"
    binary.write_bytes(b"static")
    fake_tools(monkeypatch, private_export=True)
    with pytest.raises(ValueError, match="private dependency"):
        normalizer.normalize(binary, tmp_path / "state")
    assert binary.read_bytes() == b"static"
    assert not (tmp_path / "state/receipt.json").exists()
    assert list((tmp_path / "state").glob("attempt-*/onnxruntime-original-static.a"))


def test_dynamic_runtime_requires_matching_provenance(tmp_path, monkeypatch):
    binary = tmp_path / "onnxruntime"
    binary.write_bytes(b"dynamic")
    fake_tools(monkeypatch)
    with pytest.raises(ValueError, match="no normalization provenance"):
        normalizer.normalize(binary, tmp_path / "state")


@pytest.mark.parametrize("bad", ["SourcePackages/artifacts", "../outside"])
def test_processed_output_scope_rejects_package_sources_and_outside_paths(tmp_path, bad):
    with pytest.raises(ValueError):
        normalizer.scoped_paths({"BUILT_PRODUCTS_DIR": str(tmp_path / bad),
                                 "DERIVED_FILE_DIR": str(tmp_path / "derived")}, tmp_path)


def test_processed_framework_rejects_source_symlink(tmp_path):
    source = tmp_path / "SourcePackages/artifact"
    source.parent.mkdir()
    source.write_bytes(b"static")
    binary = tmp_path / "products/onnxruntime.framework/Versions/A/onnxruntime"
    binary.parent.mkdir(parents=True)
    binary.symlink_to(source)
    with pytest.raises(ValueError, match="redirects"):
        normalizer.scoped_paths({"BUILT_PRODUCTS_DIR": str(tmp_path / "products"),
                                 "DERIVED_FILE_DIR": str(tmp_path / "derived")}, tmp_path)
