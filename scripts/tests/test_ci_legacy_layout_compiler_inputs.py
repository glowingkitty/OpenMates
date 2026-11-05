# contract-test-file: infrastructure
"""Inert exact legacy fixture compiler closure, with no compiler/container runs."""
import hashlib
from types import SimpleNamespace
import pytest
from scripts import ci_native_dev as native
from scripts import ci_sdk_conformance as sdk

FIXTURE = "backend/tests/fixtures/encryption_compatibility/legacy_layouts.json"


def test_sdk_includes_only_the_exact_external_fixture():
    assert sdk.INPUTS.count(FIXTURE) == 1
    assert "backend/tests" not in sdk.INPUTS
    assert "backend/tests/fixtures" not in sdk.INPUTS
    assert "backend/tests/fixtures/encryption_compatibility" not in sdk.INPUTS


def test_native_owns_exact_fixture_and_refuses_neighbor_paths():
    assert FIXTURE in native.EXTRA and native.owned(FIXTURE)
    for name in (FIXTURE + "/child", FIXTURE + ".other", "backend/tests/fixtures/encryption_compatibility/other.json", "backend/tests/other.py", "../" + FIXTURE):
        assert not native.owned(name)


def git_fixture(monkeypatch, module, rows):
    """Actual parsers consume finite immutable-Git wire responses, not processes."""
    data = {name: b"frozen synthetic fixture" for name in rows}
    oids = {name: hashlib.sha1(name.encode()).hexdigest() for name in rows}

    def listing(command, **kwargs):
        assert command[:3] == ["git", "ls-tree", "-r"]
        assert FIXTURE in command
        return b"".join(b"100644 blob " + oids[name].encode() + b"\t" + name.encode() + b"\0" for name in rows)

    def batch(command, **kwargs):
        assert command[:2] == ["git", "cat-file"]
        wanted = kwargs["input"].decode().splitlines()
        names = [next(name for name, oid in oids.items() if oid == value) for value in wanted]
        if command[2] == "--batch-check":
            raw = b"".join(f"{oids[name]} blob {len(data[name])}\n".encode() for name in names)
        else:
            assert command[2] == "--batch"
            raw = b"".join(f"{oids[name]} blob {len(data[name])}\n".encode() + data[name] + b"\n" for name in names)
        return SimpleNamespace(stdout=raw)

    monkeypatch.setattr(module.subprocess, "check_output", listing)
    monkeypatch.setattr(module.subprocess, "run", batch)
    return data


def test_sdk_git_input_parser_binds_fixture_bytes(monkeypatch, tmp_path):
    data = git_fixture(monkeypatch, sdk, [FIXTURE])
    result = sdk.source_inputs_from_git(tmp_path, "1" * 40)
    assert result == {FIXTURE: hashlib.sha256(data[FIXTURE]).hexdigest()}


def native_required_names():
    return sorted(set(native.EXTRA) | {root + suffix for root in native.ROOTS for suffix in ("/Cargo.toml", "/Cargo.lock")} | {native.CLI + "/src/main.rs", native.CLI + "/src/bin/tui-benchmark.rs", native.SDK + "/src/lib.rs"})


def test_native_git_input_parser_binds_fixture_bytes(monkeypatch, tmp_path):
    data = git_fixture(monkeypatch, native, native_required_names())
    result = native.source_inputs_from_git(tmp_path, "1" * 40)
    assert result[FIXTURE] == hashlib.sha256(data[FIXTURE]).hexdigest()
    assert native.EXTRA.issubset(result)


def test_native_missing_required_fixture_refuses(monkeypatch, tmp_path):
    git_fixture(monkeypatch, native, [name for name in native_required_names() if name != FIXTURE])
    with pytest.raises(sdk.Refused):
        native.source_inputs_from_git(tmp_path, "1" * 40)


def test_fixture_symlink_still_refuses(tmp_path):
    target = tmp_path / "target.json"
    target.write_bytes(b"frozen synthetic fixture")
    link = tmp_path / "legacy_layouts.json"
    link.symlink_to(target)
    with pytest.raises(sdk.Refused):
        sdk.regular(link)
