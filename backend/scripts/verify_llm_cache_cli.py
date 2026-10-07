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
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--resume-chat", help="Continue an already completed, paid first turn")
    parser.add_argument("--prior-proof", type=Path, help="Retained numeric proof of the paid first turn")
    parser.add_argument("--capture-script", type=Path)
    parser.add_argument("--target-commit")
    parser.add_argument("--cli-path", type=Path, help="Exact deployed source CLI build; defaults to installed openmates")
    args = parser.parse_args()
    if args.capture_script and not args.target_commit:
        parser.error("--capture-script requires --target-commit")
    if bool(args.resume_chat) != bool(args.prior_proof) or (args.resume_chat and not args.model):
        parser.error("--resume-chat requires --prior-proof and --model")
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
                raise RuntimeError("Retained first-turn proof belongs to another chat")
            chat = args.resume_chat
            saved = run_cli(["chats", "show", chat], model + "-saved-first", True)
            answers = [message for message in saved.get("messages", [])
                       if message.get("role") == "assistant" and message.get("content")]
            if len(answers) != 1:
                raise RuntimeError("Resumed chat must contain exactly one saved answer")
            first = {"modelName": answers[0].get("modelName")}
            after_first = before
        else:
            first = run_cli(["chats", "new", f"@{model} Explain in two short sentences why Earth has seasons. Use your existing knowledge.", "--project", project, "--response-timeout-seconds", "180"], model + "-first", True)
            if first.get("status") != "completed" or not first.get("assistant"):
                raise RuntimeError("First turn did not produce a completed answer")
            chat = first["chatId"]
            after_first = balance(model + "-after-first")
        followup = run_cli(["chats", "send", "--chat", chat, f"@{model} How does that explain opposite seasons in the northern and southern hemispheres? Answer in two short sentences.", "--response-timeout-seconds", "180"], model + "-followup", True)
        if followup.get("status") != "completed" or not followup.get("assistant"):
            raise RuntimeError("Follow-up did not produce a completed answer")
        after = balance(model + "-after-followup")
        details = run_cli(["settings", "billing", "usage", "details", "--type", "chat", "--identifier", chat, "--month", time.strftime("%Y-%m", time.gmtime())], model + "-usage")
        rows = details.get("entries", [])
        if len(rows) != 2:
            raise RuntimeError(f"Expected two inference entries, received {len(rows)}")
        total = sum(int(row["credits"]) for row in rows)
        history_after = run_cli(["settings", "billing", "usage"], model + "-history-after")["usage"]
        if prior and (not any(row["id"] == prior["chat_ask"]["id"]
                             and int(row["credits"]) == prior["chat_ask"]["credits"] for row in rows)
                      or prior["wallet_before"] - prior["wallet_after"]
                      != prior["chat_ask"]["credits"] + prior["project_recommendation"]["credits"]):
            raise RuntimeError("Saved first-turn charge does not match its retained wallet proof")
        reconciled = reconcile_new_usage(
            history_before, history_after, chat, rows, before - after,
            known_prior_chat_ids={prior["chat_ask"]["id"]} if prior else None,
        )
        for row in rows:
            receipt = row.get("llm_usage_breakdown")
            if args.require_receipts and not receipt:
                raise RuntimeError("Active cache tariff did not persist a receipt")
            if receipt and (receipt["credits_charged"] != int(row["credits"])
                            or receipt.get("settlement_state") != "settled"
                            or expected_receipt_credits(receipt) != int(row["credits"])):
                raise RuntimeError("Receipt category arithmetic differs from committed debit")
        overview = run_cli(["settings", "billing", "overview"], model + "-holds")
        if overview.get("held_credits", 0) != 0:
            raise RuntimeError("Completed requests left held credits")
        ordered = sorted(rows, key=lambda row: row["created_at"])
        measured = {"model": model, "chat_id": chat,
                    "first_credits": int(ordered[0]["credits"]),
                    "followup_credits": int(ordered[1]["credits"]), "persisted_credits": total,
                    "first_wallet_debit": (prior["wallet_before"] - prior["wallet_after"]
                                           if prior else before - after_first),
                    "followup_wallet_debit": after_first - after,
                    "usage_entries": len(rows), "held_credits": overview.get("held_credits"),
                    "first_model": first.get("modelName"), "followup_model": followup.get("modelName"),
                    "resumed_first_turn": bool(prior), "reconciliation": reconciled}
        report["models"].append(measured)
        report["ending_credits"] = after
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print("VERIFIED: " + json.dumps(measured, sort_keys=True), flush=True)
        if starting - after > 1000:
            raise RuntimeError("Test credit budget exceeded; stopping further calls")
    print("Real CLI chat and billing checks passed.", flush=True)


if __name__ == "__main__":
    main()
