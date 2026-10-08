#!/usr/bin/env python3
"""Bounded real-inference CLI billing proof, run on dev in isolated test state.

Use an authenticated disposable account and a fresh Project. Copy this script
to the temporary test source folder before execution through cli_video_capture.
Raw account responses stay private; recorded chat prompts are public synthetic text.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

MODELS = ["Gemini-3.8-Flash", "GPT-6.1-Sol", "Claude-Sonnet-5", "Mistral-Small-4"]
_NODE_WARNING = re.compile(r"^\(node:\d+\) MaxListenersExceededWarning: .*$")


def parse_cli_json(stdout: str) -> dict:
    """Parse CLI JSON after the known Node warning echoed by a terminal PTY."""
    lines = stdout.splitlines()
    while lines and (_NODE_WARNING.fullmatch(lines[0]) or
                     lines[0].startswith("(Use `node --trace-warnings ...`")):
        lines.pop(0)
    result = json.loads("\n".join(lines))
    if not isinstance(result, dict):
        raise ValueError("CLI JSON response must be an object")
    return result


def expected_receipt_credits(receipt: dict) -> int:
    """Independent rational check using the frozen public category rates."""
    raw = Fraction(0)
    for entry in receipt["entries"]:
        counts = {"input": entry["billed_input_tokens"], "output": entry["output_tokens"]}
        if entry.get("billing_mode") == "cache_aware":
            counts["cache_read"] = entry.get("cache_read_input_tokens") or 0
            if entry.get("write_billing") == "separate":
                counts["cache_write"] = entry.get("cache_creation_5m_input_tokens") or 0
                counts["cache_write_1h"] = entry.get("cache_creation_1h_input_tokens") or 0
        for category, count in counts.items():
            if count:
                raw += Fraction(count) / Fraction(entry["rates"][category])
    return max(1, raw.numerator // raw.denominator)


def full_input_flat_estimate(receipt: dict) -> int:
    """Reprice the same usage at each attempt's frozen ordinary input/output rates.

    This is a full-input counterfactual, not an exact replay of legacy billing:
    some providers formerly omitted cache writes or paid output categories.
    """
    raw = sum(
        (Fraction(entry["input_tokens"]) / Fraction(entry["rates"]["input"])
         + Fraction(entry["output_tokens"]) / Fraction(entry["rates"]["output"]))
        for entry in receipt["entries"]
    )
    return max(1, raw.numerator // raw.denominator)


def summarize_turns(rows: list[dict], *, require_receipts: bool,
                    expected_tariffs: dict | None = None) -> list[dict]:
    """Check each persisted settled charge and expose a bounded comparison."""
    turns = []
    for row in sorted(rows, key=lambda item: (item["created_at"], item["id"])):
        credits = int(row["credits"])
        receipt = row.get("llm_usage_breakdown")
        if not receipt:
            if require_receipts:
                raise RuntimeError("Active cache tariff did not persist a receipt")
            turns.append({"usage_id": row["id"], "actual_credits": credits,
                          "flat_full_input_estimate_credits": None})
            continue
        if (receipt["credits_charged"] != credits
                or receipt.get("settlement_state") != "settled"
                or expected_receipt_credits(receipt) != credits):
            raise RuntimeError("Receipt category arithmetic differs from committed debit")
        entries = receipt["entries"]
        if expected_tariffs is not None:
            if receipt.get("usage_source") != "provider_reported" or not entries:
                raise RuntimeError("Expected-tariff proof requires provider-reported usage and frozen attempts")
            for entry in entries:
                expected = expected_tariffs.get(entry["model_id"])
                if (not isinstance(expected, dict)
                        or entry.get("pricing_version") != expected.get("pricing_version")
                        or entry.get("inference_host") not in expected.get("eligible_hosts", [])):
                    raise RuntimeError("Frozen attempt differs from expected activated tariff or eligible host")
                if entry["billing_mode"] == "ordinary_input":
                    if (entry.get("cache_read_input_tokens") is not None
                            and entry.get("cache_creation_input_tokens") is not None):
                        raise RuntimeError("Ordinary-input attempt has no missing cache metric")
                elif entry["billing_mode"] != "cache_aware":
                    raise RuntimeError("Unknown frozen attempt billing mode")
        elif require_receipts and (not entries or any(entry["billing_mode"] != "cache_aware"
                                                  for entry in entries)):
            raise RuntimeError("Activated proof requires every frozen attempt to use cache-aware billing")
        turns.append({
            "usage_id": row["id"], "actual_credits": credits,
            "flat_full_input_estimate_credits": full_input_flat_estimate(receipt),
            "input_tokens": receipt["input_tokens"], "output_tokens": receipt["output_tokens"],
            "cache_read_input_tokens": receipt.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": receipt.get("cache_creation_input_tokens"),
            "pricing_versions": sorted({entry["pricing_version"] for entry in entries}),
            "billing_modes": sorted({entry["billing_mode"] for entry in entries}),
            "ordinary_input_missing_cache_metric_attempts": sum(
                entry["billing_mode"] == "ordinary_input" for entry in entries),
            "frozen_rates": [{"model_id": entry["model_id"], "rates": entry["rates"]}
                             for entry in entries],
        })
    return turns


def reconcile_new_usage(before: list[dict], after: list[dict], chat: str,
                        chat_rows: list[dict], wallet_debit: int,
                        *, known_prior_chat_ids: set[str] | None = None) -> dict:
    """Account for chat inference and the CLI's separate Project assessment."""
    history_before_ids = {row["id"] for row in before}
    if before and len(after) >= 10 and not history_before_ids.intersection(row["id"] for row in after):
        raise RuntimeError("Usage history rolled over; cannot reconcile the complete debit")
    before_ids = history_before_ids | (known_prior_chat_ids or set())
    new = [row for row in after if row["id"] not in before_ids]
    chat_ids = {row["id"] for row in chat_rows}
    inference = []
    recommendations = []
    for row in new:
        if (row["id"] in chat_ids and row.get("chat_id") == chat
                and row.get("app_id") == "ai" and row.get("skill_id") == "ask"):
            inference.append(row)
        elif (row.get("source") == "direct" and row.get("app_id") == "ai"
              and row.get("skill_id") == "project-recommendation"
              and not row.get("chat_id") and not row.get("message_id")):
            recommendations.append(row)
        else:
            raise RuntimeError("Unexpected new usage charge; cannot attribute the wallet debit")
    if {row["id"] for row in inference} != chat_ids - before_ids:
        raise RuntimeError("New inference charge is missing from account usage history")
    chat_credits = sum(int(row["credits"]) for row in inference)
    project_credits = sum(int(row["credits"]) for row in recommendations)
    if wallet_debit != chat_credits + project_credits or chat_credits <= 0:
        raise RuntimeError("Wallet debit differs from all persisted charges")
    return {"chat_credits": chat_credits, "project_recommendation_credits": project_credits,
            "wallet_debit": wallet_debit, "new_usage_entries": len(new)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--require-receipts", action="store_true")
    parser.add_argument("--expected-tariffs", type=Path,
                        help="JSON map of model IDs to deployed frozen pricing_version and eligible_hosts")
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--followup-count", type=int, choices=(1, 2), default=2)
    parser.add_argument("--resume-chat", help="Continue an already paid partial conversation")
    parser.add_argument("--prior-proof", type=Path, help="Retained numeric proof of its paid turns")
    parser.add_argument("--capture-script", type=Path)
    parser.add_argument("--target-commit")
    parser.add_argument("--cli-path", type=Path, help="Exact deployed source CLI build; defaults to installed openmates")
    args = parser.parse_args()
    if args.capture_script and not args.target_commit:
        parser.error("--capture-script requires --target-commit")
    if bool(args.resume_chat) != bool(args.prior_proof) or (args.resume_chat and not args.model):
        parser.error("--resume-chat requires --prior-proof and --model")
    expected_tariffs = json.loads(args.expected_tariffs.read_text()) if args.expected_tariffs else None
    if expected_tariffs is not None and not isinstance(expected_tariffs, dict):
        parser.error("--expected-tariffs must contain a model-ID object map")
    require_receipts = args.require_receipts or expected_tariffs is not None
    state = Path(os.environ["OPENMATES_STATE_DIR"])
    output = state / args.phase
    output.mkdir(mode=0o700, exist_ok=True)
    source = state / "test-source"
    source.mkdir(mode=0o700, exist_ok=True)
    project = json.loads((state / "test-project.private.json").read_text())["project"]["project_id"]
    executable = ["node", str(args.cli_path.resolve())] if args.cli_path else ["openmates"]
    command = executable + ["--api-url", "https://api.dev.openmates.org"]

    def run_cli(argv: list[str], name: str, visible: bool = False) -> dict:
        invocation = command + argv + ["--json"]
        if visible:
            print("\n$ " + shlex.join(invocation), flush=True)
        raw_file = output / (name + ".private.json")
        stdout_file = output / (name + ".stdout.private.txt")
        error_file = output / (name + ".stderr.private.txt")
        def retain_response(stdout: str) -> dict:
            stdout_file.write_text(stdout)
            stdout_file.chmod(0o600)
            try:
                result = parse_cli_json(stdout)
            except (json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(f"CLI command {name} returned invalid JSON; raw output retained") from exc
            raw_file.write_text(json.dumps(result) + "\n")
            raw_file.chmod(0o600)
            error = result.get("error")
            if error:
                code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
                raise RuntimeError(f"CLI command {name} returned {code}; raw output retained")
            return result
        if visible and args.capture_script:
            capture_dir = output / (name + "-capture")
            capture = subprocess.run(
                ["python3", str(args.capture_script), "--output-dir", str(capture_dir),
                 "--target-environment", "OpenMates dev " + args.target_commit,
                 "--classification", "cache-pricing-" + args.phase,
                 "--timeout-seconds", "240", "--", *invocation],
                cwd=source, capture_output=True, text=True, timeout=300,
            )
            capture_result = output / (name + ".capture.private.json")
            capture_result.write_text(capture.stdout)
            capture_result.chmod(0o600)
            error_file.write_text(capture.stderr)
            error_file.chmod(0o600)
            proof = json.loads(capture.stdout)
            manifest = proof.get("manifest", {})
            print("CAPTURED: " + json.dumps({"command": name, "status": proof["status"],
                                            "video_path": manifest.get("video_path")}), flush=True)
            if capture.returncode:
                raise RuntimeError(f"Recorded CLI command failed: {name}; proof retained")
            stdout = Path(manifest["command_output_path"]).read_text()
            return retain_response(stdout)
        with error_file.open("w") as errors:
            error_file.chmod(0o600)
            child = subprocess.Popen(invocation, stdout=subprocess.PIPE, stderr=errors, text=True, cwd=source)
            assert child.stdout is not None
            chunks = []
            # Relay the current child output to the actual recorded terminal.
            # Never replay output or render terminal pixels from a prior run.
            while chunk := child.stdout.read(1):
                chunks.append(chunk)
                if visible:
                    print(chunk, end="", flush=True)
            child.wait(timeout=240)
        stdout = "".join(chunks)
        stdout_file.write_text(stdout)
        stdout_file.chmod(0o600)
        if child.returncode:
            raise RuntimeError(f"CLI command failed: {name}; private error retained")
        return retain_response(stdout)

    def balance(label: str) -> int:
        credits = run_cli(["whoami"], label)["credits"]
        if type(credits) is not int:
            raise RuntimeError("Balance is not an integer")
        return credits

    starting = balance("phase-start-balance")
    report: dict = {"phase": args.phase, "starting_credits": starting, "models": []}
    for model in ([args.model] if args.model else MODELS):
        before = balance(model + "-before")
        history_before = run_cli(["settings", "billing", "usage"], model + "-history-before")["usage"]
        prior = None
        if args.resume_chat:
            prior = json.loads(args.prior_proof.read_text())
            if prior["chat_id"] != args.resume_chat:
                raise RuntimeError("Retained proof belongs to another chat")
            chat = args.resume_chat
            saved = run_cli(["chats", "show", chat], model + "-saved-first", True)
            answers = [message for message in saved.get("messages", [])
                       if message.get("role") == "assistant" and message.get("content")]
            paid_turns = prior.get("paid_turns", 1)
            if len(answers) != paid_turns or paid_turns > args.followup_count:
                raise RuntimeError("Saved answers differ from retained paid-turn proof")
            first = {"modelName": answers[0].get("modelName")}
            after_first = before
        else:
            first = run_cli(["chats", "new", f"@{model} Explain in two short sentences why Earth has seasons. Use your existing knowledge.", "--project", project, "--response-timeout-seconds", "180"], model + "-first", True)
            if first.get("status") != "completed" or not first.get("assistant"):
                raise RuntimeError("First turn did not produce a completed answer")
            chat = first["chatId"]
            after_first = balance(model + "-after-first")
            paid_turns = 1
        month = time.strftime("%Y-%m", time.gmtime())

        def checkpoint(completed_turns: int, current_balance: int, wallet_debits: list[int]) -> None:
            """Retain numeric proof before another paid request can begin."""
            detail = run_cli(["settings", "billing", "usage", "details", "--type", "chat",
                              "--identifier", chat, "--month", month],
                             model + f"-checkpoint-{completed_turns}")
            paid_rows = detail.get("entries", [])
            if len(paid_rows) != completed_turns:
                raise RuntimeError("Completed chat has missing persisted charges")
            summarize_turns(paid_rows, require_receipts=require_receipts,
                            expected_tariffs=expected_tariffs)
            current_history = run_cli(["settings", "billing", "usage"],
                                      model + f"-checkpoint-history-{completed_turns}")["usage"]
            previous_charges = prior.get("charges") or [prior["chat_ask"]] if prior else []
            delta = reconcile_new_usage(
                history_before, current_history, chat, paid_rows, before - current_balance,
                known_prior_chat_ids={row["id"] for row in previous_charges},
            )
            project_credits = (prior["project_recommendation"]["credits"] if prior else 0)
            project_credits += delta["project_recommendation_credits"]
            initial_balance = prior["wallet_before"] if prior else before
            if initial_balance - current_balance != sum(int(row["credits"]) for row in paid_rows) + project_credits:
                raise RuntimeError("Checkpoint does not reconcile the full paid conversation")
            proof = {"chat_id": chat, "paid_turns": completed_turns,
                     "charges": [{"id": row["id"], "credits": int(row["credits"])} for row in paid_rows],
                     "project_recommendation": {"credits": project_credits},
                     "wallet_before": initial_balance, "wallet_after": current_balance,
                     "turn_wallet_debits": wallet_debits}
            path = output / (model + "-resume-proof.private.json")
            path.write_text(json.dumps(proof, indent=2) + "\n")
            path.chmod(0o600)

        followups = [
            "How does that explain opposite seasons in the northern and southern hemispheres? Answer in two short sentences.",
            "Give me one simple example using June and December that I could tell a child. Keep it to two sentences.",
        ]
        wallet_positions = [before, after_first] if not prior else [before]
        wallet_debits = ((prior.get("turn_wallet_debits") or
                          [prior["wallet_before"] - prior["wallet_after"]]) if prior else
                         [before - after_first])
        if not prior:
            checkpoint(1, after_first, wallet_debits)
        followup_models = []
        for index in range(paid_turns - 1, args.followup_count):
            followup = run_cli(["chats", "send", "--chat", chat, f"@{model} {followups[index]}",
                                "--response-timeout-seconds", "180"],
                               model + f"-followup-{index + 1}", True)
            if followup.get("status") != "completed" or not followup.get("assistant"):
                raise RuntimeError("Follow-up did not produce a completed answer")
            followup_models.append(followup.get("modelName"))
            wallet_positions.append(balance(model + f"-after-followup-{index + 1}"))
            wallet_debits.append(wallet_positions[-2] - wallet_positions[-1])
            checkpoint(index + 2, wallet_positions[-1], wallet_debits)
            if (prior["wallet_before"] if prior else starting) - wallet_positions[-1] > 1000:
                raise RuntimeError("Test credit budget exceeded; stopping further calls")
        after = wallet_positions[-1]
        details = run_cli(["settings", "billing", "usage", "details", "--type", "chat", "--identifier", chat, "--month", month], model + "-usage")
        rows = details.get("entries", [])
        if len(rows) != args.followup_count + 1:
            raise RuntimeError(f"Expected {args.followup_count + 1} inference entries, received {len(rows)}")
        total = sum(int(row["credits"]) for row in rows)
        history_after = run_cli(["settings", "billing", "usage"], model + "-history-after")["usage"]
        if prior:
            prior_charges = prior.get("charges") or [prior["chat_ask"]]
            if (any(not any(row["id"] == charge["id"]
                            and int(row["credits"]) == charge["credits"] for row in rows)
                    for charge in prior_charges)
                    or prior["wallet_before"] - prior["wallet_after"]
                    != sum(charge["credits"] for charge in prior_charges)
                    + prior["project_recommendation"]["credits"]):
                raise RuntimeError("Saved paid charges do not match retained wallet proof")
        reconciled = reconcile_new_usage(
            history_before, history_after, chat, rows, before - after,
            known_prior_chat_ids={charge["id"] for charge in prior_charges} if prior else None,
        )
        turns = summarize_turns(rows, require_receipts=require_receipts,
                                expected_tariffs=expected_tariffs)
        overview = run_cli(["settings", "billing", "overview"], model + "-holds")
        if overview.get("held_credits", 0) != 0:
            raise RuntimeError("Completed requests left held credits")
        prior_count = prior.get("paid_turns", 1) if prior else 0
        measured = {"model": model, "chat_id": chat,
                    "first_credits": turns[0]["actual_credits"],
                    "followup_credits": turns[1]["actual_credits"], "persisted_credits": total,
                    "first_wallet_debit": wallet_debits[0],
                    "followup_wallet_debit": sum(wallet_debits[1:]),
                    "turn_wallet_debits": wallet_debits,
                    "full_wallet_debit": (prior["wallet_before"] if prior else before) - after,
                    "usage_entries": len(rows), "held_credits": overview.get("held_credits"),
                    "first_model": first.get("modelName"), "followup_models": followup_models,
                    "resumed_paid_turns": prior_count, "reconciliation": reconciled,
                    "turns": turns,
                    "flat_full_input_estimate_credits": (sum(turn["flat_full_input_estimate_credits"] for turn in turns)
                                                         if all(turn["flat_full_input_estimate_credits"] is not None for turn in turns)
                                                         else None),
                    "comparison_basis": "same usage, frozen receipt input/output rates; full inclusive input and paid output",
                    "legacy_exact_comparison": "unavailable: legacy Anthropic cache writes and Google paid output could be omitted; differences are not all cache savings"}
        report["models"].append(measured)
        report["ending_credits"] = after
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print("VERIFIED: " + json.dumps(measured, sort_keys=True), flush=True)
        if (prior["wallet_before"] if prior else starting) - after > 1000:
            raise RuntimeError("Test credit budget exceeded; stopping further calls")
    print("Real CLI chat and billing checks passed.", flush=True)


if __name__ == "__main__":
    main()
