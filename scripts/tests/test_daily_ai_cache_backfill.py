"""Focused tests for receipt-gated nightly cache backfill orchestration.

The suite proves deterministic selection, durable one-attempt claims, content
hashes, candidate replay, rollback, and promotion without provider access.
"""

# contract-test-file: tooling

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "daily_ai_cache_backfill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("daily_ai_cache_backfill_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def receipt(module, plan, mode, **overrides):
    data = {
        "schema_version": 1,
        "mode": mode,
        "candidate_run_id": plan.candidate_run_id,
        "spec": plan.spec,
        "cache_group": plan.cache_group,
        "status": "passed",
        "expected_groups": [plan.cache_group],
        "cache_files": 1,
        "cache_sha256": "a" * 64,
        "estimated_eur": 0.01,
        "real_provider_calls": 1 if mode == "record" else 0,
        "replay_misses": 0,
    }
    data.update(overrides)
    data["receipt_sha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return data


def candidate_hash(module, candidate):
    return module._cache_digest(candidate, sorted(candidate.rglob("*.json")))


def test_backfill_selects_one_deterministic_pending_spec():
    module = load_module()
    entries = [
        {"spec": "b.spec.ts", "classification": "backfill_pending", "cache_group": "b"},
        {"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"},
    ]

    first = module.select_backfill_plan(entries, "2026-08-31")

    assert first == module.select_backfill_plan(entries, "2026-08-31")
    assert first.candidate_run_id.startswith("daily-cache-backfill-20260831-")
    assert module.select_backfill_plan([], "2026-08-31") is None


def test_receipts_fail_closed_for_private_fields_hash_misses_and_replay_spend():
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )

    module.validate_receipt(receipt(module, plan, "record"), plan, mode="record")
    invalid = receipt(module, plan, "replay", replay_misses=1)
    try:
        module.validate_receipt(invalid, plan, mode="replay")
        assert False, "expected receipt validation failure"
    except module.BackfillValidationError as exc:
        assert "zero real calls" in str(exc)
    private = receipt(module, plan, "record", user_id="not allowed")
    try:
        module.validate_receipt(private, plan, mode="record")
        assert False, "expected receipt validation failure"
    except module.BackfillValidationError as exc:
        assert "forbidden fields" in str(exc)


def test_build_receipt_aggregates_worker_counters_and_candidate_files(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    run_root = tmp_path / plan.candidate_run_id
    receipt_dir = run_root / "receipts"
    group = run_root / "cache" / "a" / "llm__example"
    receipt_dir.mkdir(parents=True)
    group.mkdir(parents=True)
    (group / "entry.json").write_text(
        json.dumps({"group_id": "a", "response": {"headers": {"content-type": "application/json"}}}),
        encoding="utf-8",
    )
    (receipt_dir / "task-1.json").write_text(
        json.dumps({
            "mode": "record",
            "run_id": plan.candidate_run_id,
            "task_id": "task-1",
            "cache_hits": 0,
            "cache_misses": 1,
            "real_provider_calls": 1,
            "estimated_eur": 0.02,
        }),
        encoding="utf-8",
    )

    aggregated, candidate_group = module.build_receipt(run_root, plan, mode="record")

    assert candidate_group == run_root / "cache" / "a"
    assert aggregated["cache_files"] == 1
    assert aggregated["real_provider_calls"] == 1
    assert aggregated["estimated_eur"] == 0.02
    assert aggregated["receipt_sha256"] == module._receipt_digest(aggregated)


def test_promotion_waits_for_record_and_replay_then_updates_both_roots(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    candidate = tmp_path / "candidate" / "a"
    candidate.mkdir(parents=True)
    (candidate / "entry.json").write_text('{"group_id":"a"}', encoding="utf-8")
    calls = []

    def dispatch(spec, record, run_id):
        calls.append((spec, record, run_id))
        if not record:
            assert not (tmp_path / "runtime" / "a").exists()
        return receipt(
            module,
            plan,
            "record" if record else "replay",
            cache_sha256=candidate_hash(module, candidate),
        ), candidate

    result = module.run_backfill(
        plan,
        dispatch=dispatch,
        runtime_cache_root=tmp_path / "runtime",
        source_cache_root=tmp_path / "source",
    )

    assert calls == [("a.spec.ts", True, plan.candidate_run_id), ("a.spec.ts", False, plan.candidate_run_id)]
    assert result["status"] == "runtime_promoted"
    assert (tmp_path / "runtime" / "a" / "entry.json").is_file()
    assert (tmp_path / "source" / "a" / "entry.json").is_file()


def test_failed_replay_does_not_promote_candidate(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    candidate = tmp_path / "candidate" / "a"
    candidate.mkdir(parents=True)

    def dispatch(_spec, record, _run_id):
        return receipt(module, plan, "record" if record else "replay", replay_misses=0 if record else 1), candidate

    result = module.run_backfill(
        plan,
        dispatch=dispatch,
        runtime_cache_root=tmp_path / "runtime",
        source_cache_root=tmp_path / "source",
    )

    assert result["status"] == "failed"
    assert not (tmp_path / "runtime" / "a").exists()


def test_failed_replay_restores_the_existing_runtime_cache(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    candidate = tmp_path / "candidate" / "a"
    candidate.mkdir(parents=True)
    (candidate / "entry.json").write_text("new", encoding="utf-8")
    runtime = tmp_path / "runtime"
    (runtime / "a").mkdir(parents=True)
    (runtime / "a" / "entry.json").write_text("old", encoding="utf-8")

    def dispatch(_spec, record, _run_id):
        return receipt(module, plan, "record" if record else "replay", replay_misses=0 if record else 1), candidate

    result = module.run_backfill(plan, dispatch=dispatch, runtime_cache_root=runtime, source_cache_root=tmp_path / "source")

    assert result["status"] == "failed"
    assert (runtime / "a" / "entry.json").read_text(encoding="utf-8") == "old"


def test_existing_started_claim_never_dispatches_a_second_record(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    run_root = tmp_path / plan.candidate_run_id
    run_root.mkdir()
    (run_root / "backfill-claim.json").write_text(
        json.dumps({"candidate_run_id": plan.candidate_run_id, "phase": "record_started"}),
        encoding="utf-8",
    )
    calls = []

    def dispatch(*args):
        calls.append(args)
        raise AssertionError("an existing paid claim must not dispatch another record")

    result = module.run_backfill(
        plan,
        dispatch=dispatch,
        runtime_cache_root=tmp_path / "runtime",
        source_cache_root=None,
        claim_root=run_root,
    )

    assert result["status"] == "failed"
    assert calls == []
    assert json.loads((run_root / "backfill-claim.json").read_text(encoding="utf-8"))["phase"] == "record_failed"


def test_persistence_failure_rolls_back_existing_runtime_group(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    candidate = tmp_path / "candidate" / "a"
    candidate.mkdir(parents=True)
    (candidate / "entry.json").write_text("new", encoding="utf-8")
    runtime = tmp_path / "runtime"
    (runtime / "a").mkdir(parents=True)
    (runtime / "a" / "entry.json").write_text("old", encoding="utf-8")

    def dispatch(_spec, record, _run_id):
        return receipt(
            module,
            plan,
            "record" if record else "replay",
            cache_sha256=candidate_hash(module, candidate),
        ), candidate

    def persist(_expected_cache_sha256):
        raise subprocess.TimeoutExpired("sessions.py deploy", 1)

    result = module.run_backfill(
        plan,
        dispatch=dispatch,
        runtime_cache_root=runtime,
        source_cache_root=None,
        persist=persist,
    )

    assert result["status"] == "failed"
    assert (runtime / "a" / "entry.json").read_text(encoding="utf-8") == "old"


def test_candidate_validation_rejects_private_fields_and_secret_like_content(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    run_root = tmp_path / plan.candidate_run_id
    receipt_dir = run_root / "receipts"
    group = run_root / "cache" / "a" / "llm__example"
    receipt_dir.mkdir(parents=True)
    group.mkdir(parents=True)
    (receipt_dir / "task-1.json").write_text(
        json.dumps({"mode": "record", "run_id": plan.candidate_run_id, "real_provider_calls": 1}),
        encoding="utf-8",
    )
    (group / "entry.json").write_text(
        json.dumps({"group_id": "a", "response": {"access_token": "not-allowed"}}),
        encoding="utf-8",
    )

    try:
        module.build_receipt(run_root, plan, mode="record")
        assert False, "expected private cache content rejection"
    except module.BackfillValidationError as exc:
        assert "forbidden fields" in str(exc)


def test_same_date_claim_blocks_a_different_pending_candidate(tmp_path):
    module = load_module()
    first = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    second = module.select_backfill_plan(
        [{"spec": "b.spec.ts", "classification": "backfill_pending", "cache_group": "b"}],
        "2026-08-31",
    )
    claim_root = tmp_path / "daily-20260831"
    claim_root.mkdir()
    (claim_root / "backfill-claim.json").write_text(
        json.dumps({"candidate_run_id": first.candidate_run_id, "phase": "record_failed"}),
        encoding="utf-8",
    )
    calls = []

    result = module.run_backfill(
        second,
        dispatch=lambda *args: calls.append(args),
        runtime_cache_root=tmp_path / "runtime",
        source_cache_root=None,
        claim_root=claim_root,
        candidate_run_root=tmp_path / second.candidate_run_id,
    )

    assert result["status"] == "failed"
    assert calls == []
    assert "does not match" in result["detail"]


def test_candidate_mutation_after_replay_is_rejected_before_promotion(tmp_path):
    module = load_module()
    plan = module.select_backfill_plan(
        [{"spec": "a.spec.ts", "classification": "backfill_pending", "cache_group": "a"}],
        "2026-08-31",
    )
    candidate = tmp_path / "candidate" / "a"
    candidate.mkdir(parents=True)
    entry = candidate / "entry.json"
    entry.write_text("old-candidate", encoding="utf-8")
    runtime = tmp_path / "runtime"
    (runtime / "a").mkdir(parents=True)
    (runtime / "a" / "entry.json").write_text("known-good", encoding="utf-8")

    def dispatch(_spec, record, _run_id):
        digest = candidate_hash(module, candidate)
        result = receipt(module, plan, "record" if record else "replay", cache_sha256=digest)
        if not record:
            entry.write_text("mutated-after-replay", encoding="utf-8")
        return result, candidate

    result = module.run_backfill(
        plan,
        dispatch=dispatch,
        runtime_cache_root=runtime,
        source_cache_root=None,
    )

    assert result["status"] == "failed"
    assert "changed after replay" in result["detail"]
    assert (runtime / "a" / "entry.json").read_text(encoding="utf-8") == "known-good"
