#!/usr/bin/env python3
"""One opt-in dev AI request: currency intent, real debit/history and replay.

Uses existing isolated CLI state; never enables or runs a workflow. No login,
credentials, user profile or private historical usage is written to the receipt.
Real inference belongs on dev, never CI.
"""

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid


# contract-test: direct surface=cli assertions=workflows.authoring.compact-plan,billing.credits.idempotent-charge
def test_workflow_authoring_billing() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--node", required=True)
    parser.add_argument("--cli", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    args = parser.parse_args()
    if not args.allow_paid_dev_inference or os.getenv("CI"):
        raise SystemExit("Explicit dev inference opt-in required; never run in CI")

    def call(words):
        with (args.state_dir / ".cli-command.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            started = time.perf_counter()
            result = subprocess.run(
                [args.node, args.cli, "--api-url", "https://api.dev.openmates.org", *words, "--json"],
                env={**os.environ, "OPENMATES_STATE_DIR": str(args.state_dir), "OPENMATES_PROFILE": ""},
                capture_output=True, text=True, timeout=90,
            )
            seconds = round(time.perf_counter() - started, 3)
        if result.returncode:
            raise RuntimeError(f"CLI {words[0]} failed (exit {result.returncode}); private output withheld")
        return json.loads(result.stdout), seconds

    nonce = uuid.uuid4().hex[:8]
    text = ("Every Friday at 18:00 UTC, find noise-cancelling headphones costing no more than "
            f"150 euros and send me the matching products in chat. Name it Headphone Billing QA {nonce}.")
    key = str(uuid.uuid4())
    receipt = {"revision": args.revision, "exact_input": text, "checks": {}, "cleanup": False}
    workflow_id = None
    try:
        before, _ = call(["whoami"])
        balance = before["credits"]
        old_usage, _ = call(["settings", "billing", "usage"])
        old_ids = {row["id"] for row in old_usage["usage"]}
        response, wall = call(["workflows", "input", text, "--timezone", "UTC", "--idempotency-key", key])
        workflow = response.get("workflow") or {}
        workflow_id = workflow.get("id")
        receipt.update(status=response.get("status"), cli_wall_seconds=wall,
                       authoring_metrics=response.get("authoring_metrics"), graph=workflow.get("graph"))
        assert response["status"] == "executed" and not response.get("partial_reason"), "Authoring incomplete"
        assert workflow["enabled"] is False and workflow["status"] == "disabled"
        nodes = workflow["graph"]["nodes"]
        schedule = next(n for n in nodes if n["type"] == "schedule_trigger")["config"]["schedule"]
        assert schedule == {"type": "weekly", "timezone": "UTC", "time": "18:00", "weekdays": ["friday"]}
        shopping = next(n for n in nodes if n["config"].get("app_id") == "shopping")
        request = shopping["config"]["input"]["requests"][0]
        assert request["country"] == "de" and request["max_price"] == 150, "Euro price constraint omitted"
        assert not any(n["type"] == "check" for n in nodes)
        delivery = next(n for n in nodes if n["type"] == "send_chat_message")
        assert any(b["source"] == f"$nodes.{shopping['id']}.output.results" for b in delivery["config"]["blocks"])
        receipt["checks"]["natural_language_intent"] = True
        metrics = response["authoring_metrics"]
        billing = metrics["billing"]
        assert billing["usage_complete"] and all(e["metered"] for e in billing["entries"])
        # Independently reconcile current catalog units, not provider USD estimates.
        expected = [max(1, math.floor(s["input_tokens"] / 7900)) for s in metrics["stages"]]
        expected += [max(1, math.floor(a["input_tokens"] / 450 + a["output_tokens"] / 90))
                     for a in metrics["generation_attempts"]]
        assert [e["credits_charged"] for e in billing["entries"]] == expected
        after, _ = call(["whoami"])
        debit = balance - after["credits"]
        assert debit == sum(expected) == billing["credits_charged"], "Wallet debit differs from catalog"
        receipt.update(credits_charged=debit, expected_catalog_credits=expected)
        usage, _ = call(["settings", "billing", "usage"])
        new_rows = [r for r in usage["usage"] if r["id"] not in old_ids]
        assert len(new_rows) == len(expected)
        assert sum(r["credits"] for r in new_rows) == debit
        for row in new_rows:
            assert (row["app_id"], row["skill_id"]) == ("workflows", "create-or-modify")
            assert row["model_used"] and row["input_tokens"] > 0 and row["output_tokens"] >= 0
        receipt["billing_history"] = [{k: r.get(k) for k in (
            "credits", "app_id", "skill_id", "model_used", "input_tokens", "output_tokens", "source")}
            for r in new_rows]
        receipt["checks"]["wallet_and_settings_history"] = True
        replay, replay_wall = call(["workflows", "input", text, "--timezone", "UTC", "--idempotency-key", key])
        assert replay["session_id"] == response["session_id"] and replay["workflow"]["id"] == workflow_id
        replay_balance, _ = call(["whoami"])
        replay_usage, _ = call(["settings", "billing", "usage"])
        assert replay_balance["credits"] == after["credits"]
        assert {r["id"] for r in replay_usage["usage"]} == {r["id"] for r in usage["usage"]}
        receipt.update(replay_wall_seconds=replay_wall)
        receipt["checks"]["replay_no_additional_inference_or_charge"] = True
    finally:
        if workflow_id:
            call(["workflows", "delete", workflow_id, "--yes"])
            receipt["cleanup"] = True
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as output:
            json.dump(receipt, output, indent=2)
    print(json.dumps({k: receipt.get(k) for k in (
        "exact_input", "status", "cli_wall_seconds", "credits_charged", "replay_wall_seconds", "checks", "cleanup")}, indent=2))


if __name__ == "__main__":
    test_workflow_authoring_billing()
