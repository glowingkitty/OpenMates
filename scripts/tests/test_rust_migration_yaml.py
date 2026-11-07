"""
Tests for the structured Rust migration status (docs/migration/rust/*.yml).

Covers freshness against the generator, schema/ordering/consistency validation,
the append-only performance history and the record_perf_measurement helper.

Architecture: docs/architecture/platforms/rust-migration-status.md
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import rust_migration_yaml as migration  # noqa: E402
import rust_perf_history as perf  # noqa: E402


def load_committed() -> dict:
    return {n: yaml.safe_load((ROOT / migration.DIR / n).read_text(encoding="utf-8")) for n in migration.GENERATED}


# contract-test: tooling
def test_committed_yaml_matches_generator() -> None:
    for name, data in migration.build_all().items():
        assert (ROOT / migration.DIR / name).read_text(encoding="utf-8") == migration.dump(data), f"{name} is stale"


# contract-test: tooling
def test_generation_is_deterministic() -> None:
    assert migration.build_all() == migration.build_all()


# contract-test: tooling
def test_committed_files_validate() -> None:
    assert migration.validate(load_committed()) == []


# contract-test: tooling
def test_overview_drift_is_detected() -> None:
    files = load_committed()
    files["overview.yml"]["areas"][2]["done"] += 1
    assert any("differ" in e or "percent" in e or "done+partial" in e for e in migration.validate(files))


# contract-test: tooling
def test_priority_order_is_enforced() -> None:
    files = load_committed()
    files["overview.yml"]["areas"].reverse()
    assert any("priority" in e for e in migration.validate(files))


# contract-test: tooling
def test_history_seed_is_valid_and_append_only_checked() -> None:
    history = perf.load()
    assert perf.validate(history) == []
    longer = copy.deepcopy(history)
    longer["measurements"].append(copy.deepcopy(longer["measurements"][-1]) | {"id": "2026-11-07-wasmInstances-99"})
    assert perf.is_append_only(history, longer)
    edited = copy.deepcopy(history)
    edited["measurements"][0]["value"] = 0.5
    assert not perf.is_append_only(history, edited)


# contract-test: tooling
@pytest.mark.parametrize(
    "mutation, fragment",
    [
        ({"flow": "bogus"}, "flow"),
        ({"verdict": "great"}, "verdict"),
        ({"ci95": [2.0, 1.0]}, "ci95"),
        ({"date": "2026-13-40"}, "date"),
        ({"verdict_basis": "derived", "verdict": "rust_worse"}, "derived verdict"),
        ({"confidence": "traced", "ci_job": None, "source_commit": None}, "traced"),
    ],
)
# contract-test: tooling
def test_invalid_entries_are_rejected(mutation: dict, fragment: str) -> None:
    entry = copy.deepcopy(next(e for e in perf.load()["measurements"] if e["ci95"] and e["verdict_basis"] == "derived"))
    entry.update(mutation)
    assert any(fragment in e for e in perf.validate_entry(entry))


# contract-test: tooling
def test_dates_must_not_decrease() -> None:
    history = copy.deepcopy(perf.load())
    history["measurements"].append(copy.deepcopy(history["measurements"][0]) | {"id": "2026-11-05-embedReady-09"})
    assert any("non-decreasing" in e for e in perf.validate(history))


# contract-test: tooling
def test_derive_verdict_follows_gate() -> None:
    assert perf.derive_verdict("apps", "ratio", [0.9, 1.05]) == "rust_not_worse"
    assert perf.derive_verdict("cpu", "ratio", [0.9, 1.165]) == "inconclusive"
    assert perf.derive_verdict("cpu", "ratio", [0.9, 1.14]) == "rust_not_worse"
    assert perf.derive_verdict("search", "delta_ms", None) == "unverified"


# contract-test: tooling
def test_record_helper_dry_run_emits_valid_entry() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/record_perf_measurement.py"), "--dry-run", "--flow", "apps", "--metric", "appsFlowMs",
         "--value-kind", "ratio", "--value", "1.0", "--ci", "0.95", "1.04", "--n-pairs", "12", "--date", "2026-11-08",
         "--source-commit", "abcdef1", "--evidence", "unit test", "--notes", "dry run"],
        capture_output=True, text=True, check=True,
    )
    entry = yaml.safe_load(result.stdout)[0]
    assert entry["id"] == "2026-11-08-apps-01" and entry["verdict"] == "rust_not_worse" and entry["verdict_basis"] == "derived"
    assert perf.validate_entry(entry) == []


# contract-test: tooling
def test_lanes_validate_and_all_have_status() -> None:
    lanes = migration.load_lanes()
    assert migration.validate_lanes(lanes) == []
    assert len(lanes["lanes"]) == 14
    assert all(lane["status"] in migration.LANE_STATUSES for lane in lanes["wave3_lanes"] + lanes["lanes"])


# contract-test: tooling
def test_landed_lane_needs_commit_and_status_is_required() -> None:
    lanes = copy.deepcopy(migration.load_lanes())
    lanes["lanes"][0]["status"] = "landed"
    assert any("must name a commit" in e for e in migration.validate_lanes(lanes))
    lanes["lanes"][0]["commit"] = "abc1234"
    assert migration.validate_lanes(lanes) == []
    del lanes["lanes"][1]["status"]
    assert any("status must be one of" in e for e in migration.validate_lanes(lanes))
    lanes["lanes"][2]["deps"] = ["no-such-lane"]
    assert any("unknown dependency" in e for e in migration.validate_lanes(lanes))


# contract-test: tooling
def test_spec_links_exist_in_assertion_index() -> None:
    files = load_committed()
    problems = migration.validate_spec_links(files, migration.load_lanes(), migration.load_curated(), migration.load_spec_links())
    assert problems == []


# contract-test: tooling
def test_unknown_assertion_and_missing_links_are_rejected() -> None:
    files = load_committed()
    lanes = copy.deepcopy(migration.load_lanes())
    lanes["lanes"][0]["spec_assertions"] = ["no.such.assertion"]
    del lanes["lanes"][1]["spec_gaps"]
    lanes["lanes"][2]["spec_assertions"], lanes["lanes"][2]["spec_gaps"] = [], []
    problems = migration.validate_spec_links(files, lanes, migration.load_curated(), migration.load_spec_links())
    assert any("unknown assertion id no.such.assertion" in p for p in problems)
    assert any("required" in p for p in problems)
    assert any("needs spec_assertions" in p for p in problems)


# contract-test: tooling
def test_spec_header_report_is_non_blocking_and_well_formed() -> None:
    import report_rust_spec_headers as headers

    rows = headers.report()
    assert {r["unit"] for r in rows} == set(migration.load_curated())
    assert all(r["files"] == r["with_header"] + r["without_header"] for r in rows)
    assert headers.HEADER.match("//! spec: specifications/architecture/sync#sync.client.shared-rust-policy")
    assert not headers.HEADER.match("//! spec: specifications/surfaces/cli tasks durable delivery.")


# contract-test: tooling
def test_unit_without_curated_entry_is_a_validation_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    curated = migration.load_curated()
    dropped = next(iter(curated))
    monkeypatch.setattr(migration, "load_curated", lambda: {k: v for k, v in curated.items() if k != dropped})
    built = migration.build_all()
    problems = migration.validate(built)
    assert any(dropped in p and "curated" in p.lower() or "web-app-curated" in p for p in problems)
