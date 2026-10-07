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
import shlex
import subprocess
import time

MODELS = ["Gemini-3.8-Flash", "GPT-6.1-Sol", "Claude-Sonnet-5", "Mistral-Small-4"]


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--require-receipts", action="store_true")
    parser.add_argument("--model", choices=MODELS)
    args = parser.parse_args()
    state = Path(os.environ["OPENMATES_STATE_DIR"])
    output = state / args.phase
    output.mkdir(mode=0o700, exist_ok=True)
    source = state / "test-source"
    source.mkdir(mode=0o700, exist_ok=True)
    project = json.loads((state / "test-project.private.json").read_text())["project"]["project_id"]
    command = ["openmates", "--api-url", "https://api.dev.openmates.org"]

    def run_cli(argv: list[str], name: str, visible: bool = False) -> dict:
        invocation = command + argv + ["--json"]
        if visible:
            print("\n$ " + shlex.join(invocation), flush=True)
        raw_file = output / (name + ".private.json")
        error_file = output / (name + ".stderr.private.txt")
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
        raw_file.write_text(stdout)
        raw_file.chmod(0o600)
        if child.returncode:
            raise RuntimeError(f"CLI command failed: {name}; private error retained")
        return json.loads(stdout)

    def balance(label: str) -> int:
        credits = run_cli(["whoami"], label)["credits"]
        if type(credits) is not int:
            raise RuntimeError("Balance is not an integer")
        return credits

    starting = balance("phase-start-balance")
    report: dict = {"phase": args.phase, "starting_credits": starting, "models": []}
    for model in ([args.model] if args.model else MODELS):
        before = balance(model + "-before")
        first = run_cli(["chats", "new", f"@{model} Explain in two short sentences why Earth has seasons. Use your existing knowledge.", "--project", project, "--response-timeout-seconds", "180"], model + "-first", True)
        if first.get("status") != "completed" or not first.get("assistant"):
            raise RuntimeError("First turn did not produce a completed answer")
        chat = first["chatId"]
        after_first = balance(model + "-after-first")
        followup = run_cli(["chats", "send", "--chat", chat, f"@{model} How does that explain opposite seasons in the northern and southern hemispheres? Answer in two short sentences.", "--response-timeout-seconds", "180"], model + "-followup", True)
        if followup.get("status") != "completed" or not followup.get("assistant"):
            raise RuntimeError("Follow-up did not produce a completed answer")
        after = balance(model + "-after-followup")
        details = run_cli(["settings", "billing", "usage", "details", "--type", "chat", "--identifier", chat, "--month", time.strftime("%Y-%m", time.gmtime())], model + "-usage", True)
        rows = details.get("entries", [])
        if len(rows) != 2:
            raise RuntimeError(f"Expected two inference entries, received {len(rows)}")
        total = sum(int(row["credits"]) for row in rows)
        if before - after != total or total <= 0:
            raise RuntimeError("Wallet debit differs from persisted inference charges")
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
        measured = {"model": model, "chat_id": chat, "first_credits": before - after_first,
                    "followup_credits": after_first - after, "persisted_credits": total,
                    "usage_entries": len(rows), "held_credits": overview.get("held_credits"),
                    "first_model": first.get("modelName"), "followup_model": followup.get("modelName")}
        report["models"].append(measured)
        report["ending_credits"] = after
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print("VERIFIED: " + json.dumps(measured, sort_keys=True), flush=True)
        if starting - after > 1000:
            raise RuntimeError("Test credit budget exceeded; stopping further calls")
    print("Real CLI chat and billing checks passed.", flush=True)


if __name__ == "__main__":
    main()
