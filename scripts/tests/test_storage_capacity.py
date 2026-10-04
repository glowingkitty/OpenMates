# contract-test-file: infrastructure
"""Independent capacity outcome ledger and aggregate zero-call gates."""

import argparse
import json

from scripts.storage_capacity import make_plan, payload_digest, verify


def _plan():
    return make_plan(argparse.Namespace(
        users=1, rounds=1, embeds=1, versions=1, concurrency=1,
        seed="test", profile="accelerated", duration_seconds=1,
        round_bytes=64, embed_bytes=64, version_bytes=64,
    ))


def test_target_plan_has_accepted_daily_volume() -> None:
    plan = make_plan(argparse.Namespace(
        users=1000, rounds=500, embeds=200, versions=1000, concurrency=500,
        seed="test", profile="accelerated", duration_seconds=86400,
        round_bytes=2048, embed_bytes=8192, version_bytes=4096,
    ))
    assert plan["expected"] == {"round": 500000, "embed": 200000, "version": 1000000}


def test_receipts_and_ledger_do_not_accept_seed_rows_as_capacity(tmp_path) -> None:
    plan = _plan()
    results = tmp_path / "result.jsonl"
    rows = [
        {"kind": kind, "user": 0, "number": 0, "status": "persisted", "client_crypto": True,
         "content_sha256": payload_digest("test", 0, kind, 0, 64),
         **({"child_completed": False} if kind == "round" else {}),
         **({"reconstructed_sha256": payload_digest("test", 0, kind, 0, 64)} if kind == "version" else {})}
        for kind in ("round", "embed", "version")
    ]
    rows += [{"kind": "archive_page", "cache": "cold", "ready_ms": 700, "authorized": True, "decrypted": True,
              "archive_page_ids": ["synthetic-page-1"]},
             {"kind": "meta", "max_concurrency": 1, "duration_ms": 1000,
              "hardware": {"logical_cpu_count": 2, "memory_bytes": 1024}}]
    results.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "task.json").write_text(json.dumps({"mode": "mock", "cache_hits": 2,
                                                      "cache_misses": 0, "blocked_provider_calls": 0,
                                                      "real_provider_calls": 0,
                                                      "started_at_monotonic_ns": 1,
                                                      "finished_at_monotonic_ns": 2}))
    (receipts / "project-task.json").write_text(json.dumps({"mode": "mock", "cache_hits": 1,
                                                              "cache_misses": 0, "blocked_provider_calls": 0,
                                                              "real_provider_calls": 0,
                                                              "started_at_monotonic_ns": 3,
                                                              "finished_at_monotonic_ns": 4}))
    assert verify(plan, results, receipts)["passed"] is True
    rows[2]["reconstructed_sha256"] = "wrong"
    results.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = verify(plan, results, receipts)
    assert report["passed"] is False
    assert "version reconstruction mismatch" in report["failures"]
    (receipts / "task.json").write_text(json.dumps({"mode": "mock", "cache_hits": 2,
                                                      "real_provider_calls": 1,
                                                      "started_at_monotonic_ns": 1,
                                                      "finished_at_monotonic_ns": 2}))
    assert "real provider calls observed" in verify(plan, results, receipts)["failures"]


def test_client_slots_cannot_substitute_for_server_task_overlap(tmp_path) -> None:
    plan = make_plan(argparse.Namespace(
        users=2, rounds=1, embeds=1, versions=1, concurrency=2,
        seed="test", profile="accelerated", duration_seconds=1,
        round_bytes=64, embed_bytes=64, version_bytes=64,
    ))
    rows = []
    for user in range(2):
        for kind in ("round", "embed", "version"):
            row = {"kind": kind, "user": user, "number": 0, "status": "persisted", "client_crypto": True,
                   "content_sha256": payload_digest("test", user, kind, 0, 64)}
            if kind == "round":
                row["child_completed"] = False
            if kind == "version":
                row["reconstructed_sha256"] = row["content_sha256"]
            rows.append(row)
    rows += [{"kind": "archive_page", "cache": "cold", "ready_ms": 700, "authorized": True,
              "decrypted": True, "archive_page_ids": ["page-1"]},
             {"kind": "meta", "max_concurrency": 2, "duration_ms": 1000,
              "hardware": {"logical_cpu_count": 2, "memory_bytes": 1024}}]
    results = tmp_path / "result.jsonl"
    results.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    for index, (started, finished) in enumerate(((1, 2), (3, 4), (5, 6), (7, 8))):
        (receipts / f"task-{index}.json").write_text(json.dumps({
            "mode": "mock", "cache_hits": 1, "cache_misses": 0,
            "blocked_provider_calls": 0, "real_provider_calls": 0,
            "started_at_monotonic_ns": started, "finished_at_monotonic_ns": finished,
        }))
    report = verify(plan, results, receipts)
    assert report["observed_max_client_inflight"] == 2
    assert report["server_task_peak_concurrency"] == 1
    assert "peak server task concurrency not reached" in report["failures"]


def test_failure_report_exposes_stage_class_location_but_never_private_reason(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    private_reason = "private synthetic account or ciphertext must stay private"
    results.write_text(json.dumps({"kind": "failure", "phase": "version_callback_count",
                                   "error_class": "TypeError", "source_location":
                                   "storage_capacity_version_adapter.mjs:73", "reason": private_reason}) + "\n")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    report = verify(_plan(), results, receipts)
    assert report["passed"] is False
    assert "workload failure at version_callback_count (TypeError; storage_capacity_version_adapter.mjs:73)" in report["failures"]
    assert private_reason not in json.dumps(report)
    results.write_text(json.dumps({"kind": "failure", "phase": ["untrusted"],
                                   "error_class": private_reason, "source_location": private_reason,
                                   "reason": private_reason}) + "\n")
    report = verify(_plan(), results, receipts)
    assert "workload failure at unknown (Error; unavailable)" in report["failures"]
    assert private_reason not in json.dumps(report)


# contract-test: infrastructure

def test_sharded_receipts_preserve_independent_server_overlap(tmp_path) -> None:
    plan = make_plan(argparse.Namespace(
        users=2, rounds=1, embeds=1, versions=1, concurrency=2,
        seed="test", profile="accelerated", duration_seconds=1,
        round_bytes=64, embed_bytes=64, version_bytes=64,
    ))
    rows = []
    for user in range(2):
        for kind in ("round", "embed", "version"):
            digest = payload_digest("test", user, kind, 0, 64)
            rows.append({"kind": kind, "user": user, "number": 0, "status": "persisted",
                         "client_crypto": True, "content_sha256": digest,
                         **({"child_completed": False} if kind == "round" else {}),
                         **({"reconstructed_sha256": digest} if kind == "version" else {})})
    rows.extend([{"kind": "archive_page", "cache": "cold", "ready_ms": 20,
                  "authorized": True, "decrypted": True, "archive_page_ids": ["page"]},
                 {"kind": "meta", "max_concurrency": 2, "duration_ms": 1000,
                  "hardware": {"logical_cpu_count": 2}}])
    results = tmp_path / "results.jsonl"
    results.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    receipts = tmp_path / "receipts"
    for shard, index, (start, end) in (("aa", 0, (1, 3)), ("bb", 1, (2, 4)),
                                       ("aa", 2, (5, 6)), ("bb", 3, (7, 8))):
        directory = receipts / shard
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"task-{index}.json").write_text(json.dumps({
            "mode": "mock", "cache_hits": 1, "started_at_monotonic_ns": start,
            "finished_at_monotonic_ns": end,
        }))
    report = verify(plan, results, receipts)
    assert report["passed"] is True
    assert report["server_task_peak_concurrency"] == 2
    assert report["task_receipt_count"] == 4


# contract-test: infrastructure

def test_live_mock_capacity_writer_uses_deterministic_private_shard(tmp_path, monkeypatch) -> None:
    import hashlib
    import importlib.util
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "backend/shared/testing/mock_context.py"
    module_spec = importlib.util.spec_from_file_location("capacity_receipt_writer_under_test", source)
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, module_spec.name, module)
    module_spec.loader.exec_module(module)
    monkeypatch.setenv("OPENMATES_CAPACITY_RECEIPT_ROOT", str(tmp_path / "receipts"))
    module.activate_mock_mode("mock", "storage_capacity_v1", task_id="task-123")
    try:
        written = module.write_live_mock_receipt()
    finally:
        module.deactivate_mock_mode()
    assert written == tmp_path / "receipts" / hashlib.sha256(b"task-123").hexdigest()[:2] / "task-123.json"
    assert json.loads(written.read_text())["mode"] == "mock"
