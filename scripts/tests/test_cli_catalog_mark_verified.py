"""Tests for scripts/cli_catalog_mark_verified.py."""
# contract-test-file: tooling
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli_catalog_mark_verified as tool  # noqa: E402

SPEC = "cli-native-demo.spec.ts"


def write(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def setup(tmp_path: Path, records):
    catalog = {"commands": [
        {"path": ["demo", "a"], "gaps": ["Pending text."]},
        {"path": ["demo", "b"], "gaps": []},
        {"path": ["demo", "c"], "gaps": ["Other."]},
    ]}
    (tmp_path / "config").mkdir()
    write(tmp_path / tool.CATALOG, catalog)
    return write(tmp_path / "artifact.json", {"records": records})


def test_marks_pass_only_commands_and_is_idempotent(tmp_path):
    artifact = setup(tmp_path, [
        {"verdict": "pass", "catalog": ["demo a"]},
        {"verdict": "pass", "catalog": ["demo b"]},
        {"verdict": "pass", "catalog": []},
    ])
    assert tool.run(SPEC, [artifact], tmp_path) == ["demo a", "demo b"]
    commands = json.loads((tmp_path / tool.CATALOG).read_text())["commands"]
    assert commands[0]["gaps"] == [tool.marker(SPEC) + " Pending text."]
    assert commands[1]["gaps"] == [tool.marker(SPEC)]
    assert commands[2]["gaps"] == ["Other."]
    assert tool.run(SPEC, [artifact], tmp_path) == []


def test_respec_replaces_marker_and_keeps_rest(tmp_path):
    artifact = setup(tmp_path, [{"verdict": "pass", "catalog": ["demo a"]}])
    tool.run("old.spec.ts", [artifact], tmp_path)
    tool.run(SPEC, [artifact], tmp_path)
    gaps = json.loads((tmp_path / tool.CATALOG).read_text())["commands"][0]["gaps"]
    assert gaps == [tool.marker(SPEC) + " Pending text."]


def test_refuses_gap_unknown_and_mixed(tmp_path):
    artifact = setup(tmp_path, [
        {"verdict": "pass", "catalog": ["demo a"]},
        {"verdict": "gap", "catalog": ["demo a"]},
    ])
    with pytest.raises(ValueError, match="demo a"):
        tool.run(SPEC, [artifact], tmp_path, requested={"demo a"})
    assert tool.run(SPEC, [artifact], tmp_path) == []
    unknown = write(tmp_path / "u.json", {"records": [{"verdict": "pass", "catalog": ["demo zzz"]}]})
    with pytest.raises(ValueError, match="Unknown"):
        tool.run(SPEC, [unknown], tmp_path)
    assert json.loads((tmp_path / tool.CATALOG).read_text())["commands"][0]["gaps"] == ["Pending text."]
