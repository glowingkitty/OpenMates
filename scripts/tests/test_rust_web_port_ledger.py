"""Tests for the web Rust port ledger (scripts/rust_web_port_ledger.py) and the overview roll-ups
(scripts/rust_migration_rollup.py): line counting, routing detection, ledger completeness, the
weighted overall formula and the performance summary.

Synthetic TS fixtures live in tmp_path; the module's ROOT is monkeypatched so nothing in the
repository is read.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rust_migration_rollup as rollup  # noqa: E402 - needs the sys.path entry above
import rust_web_port_ledger as pl  # noqa: E402 - needs the sys.path entry above

SERVICE = """import { rustThing } from "./rustCore/thing";

const RUST_ON = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";

// A comment line is not a code line.
export async function routed(x: number): Promise<number> {
  if (RUST_ON) {
    return rustThing(x);
  }
  return x + 1;
}

export function plain(x: number): number {
  return x * 2;
}

export function viaBridge(): number {
  return rustThing(3);
}
"""

BRIDGE = """export function rustThing(x: number): number {
  return x;
}
"""

VOICE = """export function speak(): void {
  const on = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";
}
"""


def _ledger(slices: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "counting": {"rule": "test", "full_function_max_code_lines": 80},
        "scope": {"roots": ["ui/services"], "excluded": [{"glob": "*.test.ts", "reason": "tests"}],
                  "bridge": [{"glob": "ui/services/rustCore/*", "reason": "bridge"}]},
        "non_portable": [{"glob": "ui/services/voice.ts", "reason": "audio"}],
        "slices": slices,
    }


def _slice(functions: list[str], **extra) -> dict:
    return {"id": "s1", "commit": "abcdef1", "date": "2026-11-08", "rust": [], "vectors": [], "e2e": [],
            "ts": [{"file": "ui/services/svc.ts", "functions": functions}], **extra}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "ui/services/rustCore").mkdir(parents=True)
    (tmp_path / "ui/services/svc.ts").write_text(SERVICE, encoding="utf-8")
    (tmp_path / "ui/services/rustCore/thing.ts").write_text(BRIDGE, encoding="utf-8")
    (tmp_path / "ui/services/voice.ts").write_text(VOICE, encoding="utf-8")
    (tmp_path / "ui/services/svc.test.ts").write_text("export const x = 1;\n", encoding="utf-8")
    monkeypatch.setattr(pl, "ROOT", tmp_path)
    return tmp_path


def _measure(ledger: dict) -> tuple[dict, list[str]]:
    return pl.measure(pl.build_model(ledger))


# contract-test: tooling
def test_counts_only_ledgered_routing_lines_against_portable_scope(repo):
    summary, errors = _measure(_ledger([_slice(["routed", "viaBridge"])]))
    assert errors == []
    # svc.ts has 14 code lines (comment and blank lines excluded); bridge, non-portable and tests are out of scope.
    assert summary["portable_files"] == 1
    assert summary["portable_code_lines"] == 14
    # routed (6 code lines) + viaBridge (3); plain is not ported.
    assert summary["ported_code_lines"] == 9
    assert summary["percent"] == 64.3
    assert summary["non_portable"] == {"files": 1, "code_lines": 3}
    assert summary["bridge_excluded"] == {"files": 1, "code_lines": 3}
    assert summary["ported_by_proof"] == {"e2e-flag-on": 0, "vectors": 0, "none": 9}


# contract-test: tooling
def test_unledgered_routing_function_is_an_error(repo):
    _, errors = _measure(_ledger([_slice(["routed"])]))
    assert any("routing function without ledger entry: ui/services/svc.ts viaBridge" in e for e in errors)


# contract-test: tooling
def test_ledgered_function_that_does_not_route_is_an_error(repo):
    _, errors = _measure(_ledger([_slice(["routed", "viaBridge", "plain"])]))
    assert any("plain does not route to Rust" in e for e in errors)


# contract-test: tooling
def test_duplicate_claim_and_bad_commit_are_errors(repo):
    second = _slice(["routed"], id="s2", commit="NOT-HEX")
    _, errors = _measure(_ledger([_slice(["routed", "viaBridge"]), second]))
    assert any("already claimed by slice s1" in e for e in errors)
    assert any("commit must be a lowercase hex id or null" in e for e in errors)


# contract-test: tooling
def test_proof_level_prefers_e2e_then_vectors():
    assert pl.proof_level({"e2e": ["a.spec.ts"], "vectors": ["v.test.ts"]}) == "e2e-flag-on"
    assert pl.proof_level({"e2e": [], "vectors": ["v.test.ts"]}) == "vectors"
    assert pl.proof_level({}) == "none"


# contract-test: tooling
def test_long_function_counts_only_decision_sites(repo):
    body = "".join(f"  const v{i} = {i};\n" for i in range(100))
    text = ('const RUST_ON = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";\n'
            "export function big(): number {\n" + body
            + "  if (RUST_ON) {\n    return 1;\n  }\n  return 0;\n}\n")
    (repo / "ui/services/svc.ts").write_text(text, encoding="utf-8")
    summary, errors = _measure(_ledger([_slice(["big"])]))
    assert errors == []
    assert summary["functions_counted_at_decision_sites_only"] == 1
    assert summary["ported_code_lines"] == 3  # the if block only, not the 100 assignments


# contract-test: tooling
def test_committed_ledger_is_complete_and_counts_lines():
    summary, errors = pl.measure(pl.build_model(pl.load_ledger()))
    assert errors == []
    assert 0 < summary["ported_code_lines"] < summary["portable_code_lines"]
    assert sum(summary["ported_by_proof"].values()) == summary["ported_code_lines"]


# --- roll-ups --------------------------------------------------------------------------------

PERCENTS = {"web_app": 10.0, "shared_client": 20.0, "cli": 60.0, "sdk_rust": 9.0, "sdk_npm": 12.0, "sdk_python": 15.0}


# contract-test: tooling
def test_overall_is_weighted_average_with_sdk_mean():
    block = rollup.overall(PERCENTS)
    assert block["inputs"]["sdk"] == 12.0
    assert block["percent"] == round(0.4 * 10 + 0.2 * 20 + 0.25 * 60 + 0.15 * 12, 1) == 24.8
    assert block["weights_decided"] == "2026-11-08"
    assert rollup.validate_overall(block, PERCENTS) == []


# contract-test: tooling
def test_overall_drift_is_detected():
    block = rollup.overall(PERCENTS)
    tampered = copy.deepcopy(block)
    tampered["percent"] = 50.0
    assert rollup.validate_overall(tampered, PERCENTS)
    reweighted = copy.deepcopy(block)
    reweighted["weights"]["cli"] = 0.5
    assert rollup.validate_overall(reweighted, PERCENTS)


def _entry(id_: str, day: str, metric: str, verdict: str) -> dict:
    return {"id": id_, "date": day, "flow": "send", "metric": metric, "value_kind": "ratio", "value": 1.0,
            "ci95": [0.9, 1.1], "n_pairs": 12, "verdict": verdict, "source_commit": "abcdef1"}


# contract-test: tooling
def test_performance_keeps_latest_per_metric_and_marks_stale():
    history = {"measurements": [
        _entry("2026-11-06-send-01", "2026-11-06", "draftSaveP95Ms", "rust_not_worse"),
        _entry("2026-11-08-send-01", "2026-11-08", "draftSaveP95Ms", "rust_worse"),
        _entry("2026-11-06-send-02", "2026-11-06", "sendTotalMs", "inconclusive"),
        _entry("2026-11-07-send-01", "2026-11-07", "sendCpuMs", "rust_not_worse"),
    ]}
    block = rollup.performance(history, "2026-11-08")
    rows = {r["metric"]: r for r in block["latest"]}
    assert rows["draftSaveP95Ms"]["id"] == "2026-11-08-send-01"
    assert (rows["sendTotalMs"]["age_hours"], rows["sendTotalMs"]["stale"]) == (48, True)
    assert (rows["sendCpuMs"]["age_hours"], rows["sendCpuMs"]["stale"]) == (24, False)
    assert block["by_verdict"]["rust_worse"] == 1 and block["by_verdict"]["inconclusive"] == 1
    attention = rollup.perf_attention(block)
    assert attention[0]["metric"] == "draftSaveP95Ms"
    assert attention[0]["status"].startswith("under investigation")
    # The interval is copied, so the YAML dump writes values instead of anchors.
    assert attention[0]["ci95"] is not history["measurements"][1]["ci95"]
