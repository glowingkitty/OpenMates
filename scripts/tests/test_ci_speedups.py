"""Tests for the per-owner CI speedup switch."""
# contract-test-file: tooling

import json

from scripts import ci_speedups as cs


def test_missing_file_means_all_off(tmp_path):
    assert cs.dispatch_value("2088", tmp_path / "none.json") == ""


def test_owner_gets_default_plus_own_and_unknown_names_are_dropped(tmp_path):
    path = tmp_path / "speedups.json"
    path.write_text(json.dumps({"default": ["wasm-cache", "typo"], "owners": {"2088": ["browser-cache"]}}))
    assert cs.dispatch_value("2088", path) == "browser-cache,wasm-cache"
    assert cs.dispatch_value("other", path) == "wasm-cache"


def test_enable_and_disable_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "speedups.json"
    monkeypatch.setenv("OPENMATES_CI_SPEEDUPS_FILE", str(path))
    cs.main(["enable", "prepared-rust-core", "--owner", "1992"])
    cs.main(["enable", "wasm-cache"])
    assert cs.enabled("1992") == {"prepared-rust-core", "wasm-cache"}
    cs.main(["disable", "prepared-rust-core", "--owner", "1992"])
    assert json.loads(path.read_text()) == {"default": ["wasm-cache"], "owners": {}}


def test_unreadable_file_is_all_off(tmp_path):
    path = tmp_path / "speedups.json"
    path.write_text("{not json")
    assert cs.enabled("2088", path) == frozenset()
