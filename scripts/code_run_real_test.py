#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real Code Run proof: Python math and two Rust programs.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/code_run_real_test.py --session ID --revision FULL_SHA \
    --state-dir /tmp/code-run-state-UNIQUE --receipt /tmp/code-run-proof/receipt.json \
    --recording-dir /tmp/code-run-proof --allow-paid-dev-inference

Uses the installed global CLI and its installed SDK with ordinary automatic
routing. Never run in CI. Synthetic transcripts, recordings and receipts stay
outside the repository. Only this invocation's chats and Project are deleted.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from verify_chat_sidebar_title_live import test_account_environment
from workflow_schedule_real_test import API_URL, ProofError, acquire_leases, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"finished", "failed", "cancelled"}


def fnv1a(text: str) -> str:
    value = 14695981039346656037
    for byte in text.encode():
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"{value:016x}"


def prompts(nonce: str) -> list[dict]:
    common = (
        "Create source code embeds and automatically execute them using code.run in E2B. "
        "Do not ask me to click Run. Include the execution/task UUID returned by code.run in your acknowledgement "
        "and final explanation. Wait for the actual execution result before claiming success. "
        f"The source must calculate 64-bit FNV-1a over UTF-8 bytes of '{nonce}' "
        "(offset 14695981039346656037, prime 1099511628211, wrapping unsigned 64-bit arithmetic), "
        "and print proof=<16 lowercase hex digits>. After execution, include that exact returned proof line "
        "in your final explanation together with actual results and generated artifact references. "
    )
    return [
        {"label": "python-math", "language": "python", "artifact": "outputs/chart.png", "prompt": common +
         "Use Python with imports sympy as sp, numpy as np, matplotlib.pyplot as plt, and "
         "from IPython.display import display. Include requirements.txt for those packages. "
         "For f(x)=exp(-x*x/2)*cos(3*x), compute symbolic first and second derivatives and display them. "
         "Print f, f-prime, f-double-prime at x=0, 0.5, 1 as three lines using the exact format "
         "x=0.0 f=<number> d1=<number> d2=<number> (use x=0.5 and x=1.0 for the other rows), "
         "each value with at least 8 significant digits. Plot f and both derivatives over [-3,3] with NumPy "
         "and save outputs/chart.png. Explain the numeric results and plot from the returned execution."},
        {"label": "rust-fibonacci", "language": "rust", "artifact": None, "prompt": common +
         "Use the Rust programming language: one standalone main.rs, standard library only. "
         "Compute the first 20 Fibonacci numbers beginning F0=0,F1=1. Assert the last is 4181 and sum is 10945. "
         "Print the full sequence and the exact line count=20 last=4181 sum=10945. "
         "Explain what the actual successful assertions and terminal output establish."},
        {"label": "rust-word-count", "language": "rust", "artifact": "outputs/word_counts.csv", "prompt": common +
         "Use the Rust programming language: one standalone main.rs, standard library only. "
         "Count words case-insensitively in: Rust makes reliable tools. Rust makes fast tools. "
         "Safe tools make reliable systems. Split on nonalphabetic characters. Use a HashMap, then "
         "sort words alphabetically. Write outputs/word_counts.csv with header word,count. "
         "Print all CSV rows and the exact line total=13 unique=8. Assert tools=3, rust=2 and total=13. "
         "Explain the actual counts and link the generated CSV."},
    ]


def command(cli: str, args: list[str], *, timeout: int = 120) -> dict | list:
    result = subprocess.run([cli, *args, "--api-url", API_URL, "--json"], cwd=ROOT,
                            capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise ProofError(f"{args[0]}_{args[1]}_failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProofError("cli_json_invalid") from exc


def require_runtime_revision(revision: str) -> None:
    """Bind live evidence to the leased product source rather than a supplied label."""
    result = subprocess.run(
        ["git", "-C", str(sessions.PRODUCT_RUNTIME_CHECKOUT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if result.returncode or result.stdout.strip() != revision:
        raise ProofError("deployed_runtime_revision_mismatch")


def installed_sdk(cli: str, supplied: Path | None) -> Path:
    if supplied:
        path = supplied.resolve()
    else:
        entry = Path(cli).resolve()
        if entry.name == "cli.js":
            path = entry.with_name("index.js")
        else:
            # Managed npm installation uses a credential-free shell launcher.
            words = shlex.split(entry.read_text())
            candidates = [Path(word) for word in words if word.endswith("/dist/cli.js")]
            if len(candidates) != 1:
                raise ProofError("installed_sdk_module_required")
            path = candidates[0].with_name("index.js")
    if not path.is_file():
        raise ProofError("installed_sdk_missing")
    return path


def verify(case: dict, snapshot: dict, proof: str, nonce: str) -> tuple[bool, str]:
    embeds = snapshot.get("embeds", [])
    sources = [embed for embed in embeds if isinstance((embed.get("content") or {}).get("code"), str)]
    eligible = [embed for embed in sources if (embed["content"].get("language") == case["language"]
                or str(embed["content"].get("filename", "")).endswith(".rs" if case["language"] == "rust" else ".py"))
                and nonce in embed["content"]["code"]]
    if not eligible:
        return False, "created_code_embed_missing"
    eligible_ids = {embed["embedId"] for embed in eligible}
    executions = [run for run in snapshot.get("executions", []) if run.get("target_embed_id") in eligible_ids]
    if not executions:
        return False, "execution_status_missing"
    completed = [run for run in executions if run.get("status") == "finished" and run.get("exit_code") == 0]
    if not completed:
        return False, "execution_failed" if all(run.get("status") in TERMINAL for run in executions) else "execution_pending"
    run = completed[-1]
    output = "".join(str(event.get("text", "")) for event in run.get("events", [])
                     if event.get("kind") in {"stdout", "stderr"})
    if f"proof={proof}" not in output:
        return False, "actual_output_proof_missing"
    if case["label"] == "python-math":
        source = eligible[-1]["content"]["code"]
        if not all(package in source for package in ("sympy", "numpy", "matplotlib", "IPython")):
            return False, "math_imports_missing"
        rows = re.findall(r"x=(0\.0|0\.5|1\.0)\s+f=([-+\d.eE]+)\s+d1=([-+\d.eE]+)\s+d2=([-+\d.eE]+)", output)
        if {row[0] for row in rows} != {"0.0", "0.5", "1.0"}:
            return False, "math_evaluations_missing"
        for raw_x, *raw_values in rows:
            x = float(raw_x)
            e, c, s = math.exp(-x*x/2), math.cos(3*x), math.sin(3*x)
            expected = [e*c, e*(-x*c-3*s), e*((x*x-10)*c+6*x*s)]
            if not all(math.isclose(float(actual), value, rel_tol=1e-7, abs_tol=1e-8)
                       for actual, value in zip(raw_values, expected, strict=True)):
                return False, "math_evaluations_wrong"
    elif case["label"] == "rust-fibonacci":
        if "count=20 last=4181 sum=10945" not in output:
            return False, "fibonacci_result_missing"
    else:
        expected = ["word,count", "fast,1", "make,1", "makes,2", "reliable,2", "rust,2", "safe,1", "systems,1", "tools,3"]
        if "\n".join(expected) not in output.replace("\r\n", "\n") or "total=13 unique=8" not in output:
            return False, "word_count_result_wrong"
    if case["artifact"] and not any(
        artifact.get("normalized_path", artifact.get("path")) == case["artifact"]
        and artifact.get("status") == "captured" and artifact.get("asset_id")
        and int(artifact.get("size_bytes", 0)) > 0 for artifact in run.get("artifacts", [])
    ):
        return False, "stored_artifact_missing"
    assistants = [message for message in snapshot.get("messages", []) if message.get("role") == "assistant"]
    # Require a saved assistant answer correlated with the independently checked
    # terminal nonce, not the dispatch acknowledgement or plausible prose alone.
    explanation = next((str(message.get("content", "")) for message in reversed(assistants)
                        if f"proof={proof}" in str(message.get("content", ""))), "")
    if not explanation:
        text = json.dumps(snapshot)
        if '"scan_status": "unscanned"' in text or re.search(r"withheld|scan.{0,40}unavailable", text, re.I):
            return False, "scanner_withheld_output"
        return False, "assistant_continuation_missing"
    needed = {"python-math": ["derivative", "chart"], "rust-fibonacci": ["4181", "10945"],
              "rust-word-count": ["13", "8", "csv"]}[case["label"]]
    if not all(item.lower() in explanation.lower() for item in needed):
        return False, "assistant_explanation_incomplete"
    return True, "verified"


def flow(input_path: Path) -> int:
    state = Path(os.environ.get("OPENMATES_STATE_DIR", "/missing")).resolve()
    if not state.is_relative_to(Path("/tmp")) or not input_path.resolve().is_relative_to(Path("/tmp")):
        raise ProofError("isolated_flow_input_required")
    if not (state / "session.json").is_file() or json.loads((state / "session.json").read_text()).get("apiUrl") != API_URL:
        raise ProofError("isolated_dev_session_required")
    data = json.loads(input_path.read_text())
    case, directory = data["case"], input_path.parent
    result = {"label": case["label"], "slug": data["slug"], "status": "failed"}
    try:
        print(f"Request: {case['prompt']}\n", flush=True)
        sent = command(data["cli"], ["chats", "new", case["prompt"], "--project", data["project_id"],
                       "--slug", data["slug"], "--personal", "--response-timeout-seconds", "240"], timeout=270)
        write_receipt(directory / "initial-response.json", sent)
        chat_id = sent.get("chatId") if isinstance(sent, dict) else None
        if not isinstance(chat_id, str) or not chat_id:
            raise ProofError("created_chat_id_missing")
        result["chat_id"] = chat_id
        write_receipt(directory / "result.json", result)
        print(f"Saved chat {chat_id}; waiting for authenticated execution status and assistant continuation.", flush=True)
        deadline = time.monotonic() + data["timeout_seconds"]
        snapshot, reason = {}, "execution_status_missing"
        known_executions: list[str] = []
        while time.monotonic() < deadline:
            request = {"api_url": API_URL, "sdk_module": data["sdk_module"], "chat_id": chat_id,
                       "execution_ids": known_executions}
            probed = subprocess.run(["node", str(Path(__file__).with_name("code_run_real_probe.mjs"))],
                                    input=json.dumps(request), capture_output=True, text=True, cwd=ROOT,
                                    check=False, timeout=120)
            if probed.returncode:
                raise ProofError("authenticated_sdk_probe_failed")
            snapshot = json.loads(probed.stdout)
            write_receipt(directory / "snapshot.json", snapshot)
            known_executions = [run["execution_id"] for run in snapshot.get("executions", [])]
            passed, current = verify(case, snapshot, data["proof"], data["nonce"])
            if current != reason:
                print(f"Verification: {current}", flush=True)
                reason = current
            if passed:
                result.update(status="passed", execution_ids=known_executions, verification=current)
                for run in snapshot.get("executions", []):
                    print(f"Authenticated execution {run['execution_id']}: status={run.get('status')} exit={run.get('exit_code')}", flush=True)
                    for event in run.get("events", []):
                        if event.get("kind") in {"stdout", "stderr"}:
                            print(str(event.get("text", "")), end="", flush=True)
                    for artifact in run.get("artifacts", []):
                        print(f"Stored artifact: {artifact.get('path')} ({artifact.get('status')}, {artifact.get('size_bytes')} bytes)", flush=True)
                break
            # Let failed runs recover through the existing two bounded auto-debug
            # reruns. No extra inference or manually triggered execution is sent.
            time.sleep(min(8, max(0, deadline-time.monotonic())))
        else:
            raise ProofError(reason)
        print("Actual saved assistant conversation:", flush=True)
        shown = subprocess.run([data["cli"], "chats", "show", chat_id, "--api-url", API_URL,
                                "--personal"], cwd=ROOT, check=False, timeout=120)
        if shown.returncode:
            raise ProofError("final_conversation_cli_failed")
        print(f"Verified real code run: {case['label']}", flush=True)
    except BaseException as exc:
        result["status"] = "failed"
        result["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
        print(f"Code Run proof failed: {result['error_code']}", flush=True)
    finally:
        write_receipt(directory / "result.json", result)
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--revision", required=True, help="Exact deployed dev SHA")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--recording-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates", help="Installed global CLI executable")
    parser.add_argument("--sdk-module", type=Path, help="Installed SDK index.js, if the CLI launcher cannot identify it")
    parser.add_argument("--slot", type=int, choices=range(1, 14))
    parser.add_argument("--timeout-seconds", type=int, default=600, help="Bounded continuation wait per flow")
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    args = parser.parse_args()
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 1200:
        parser.error("explicit paid-dev opt-in and a 60–1200 second timeout required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be the full deployed dev SHA")
    state, receipt_path, recording = args.state_dir.resolve(), args.receipt.resolve(), args.recording_dir.resolve()
    if state == Path("/tmp") or not state.is_relative_to(Path("/tmp")) or state.exists():
        parser.error("--state-dir must be a fresh path below /tmp")
    for path in (receipt_path, recording):
        if not path.is_relative_to(Path("/tmp")) or path.is_relative_to(state) or path.is_relative_to(ROOT):
            parser.error("private proof paths must be below /tmp and outside CLI state/repository")
    if recording == Path("/tmp") or recording.exists():
        parser.error("--recording-dir must be a fresh private directory below /tmp")
    cli = shutil.which(args.cli)
    if not cli:
        parser.error("installed global openmates executable missing")
    try:
        sdk_module = installed_sdk(cli, args.sdk_module)
    except ProofError as exc:
        parser.error(str(exc))
    receipt = {"status": "started", "target": API_URL, "session": args.session,
               "deployed_revision": args.revision, "started_at": datetime.now(UTC).isoformat(),
               "cases": [], "cleanup": {}, "cli": cli, "sdk_module": str(sdk_module)}
    leases, project_id, created_state = [], None, False
    stop, errors = threading.Event(), []
    heartbeat = None
    old_umask = os.umask(0o077)
    try:
        state.mkdir(mode=0o700)
        created_state = True
        recording.mkdir(mode=0o700, parents=True)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        leases, slot = acquire_leases(args.session, args.slot)
        receipt["account_slot"] = slot
        require_runtime_revision(args.revision)

        def renew() -> None:
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in leases:
                    try:
                        sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)
                    except RuntimeError:
                        errors.append("lease_renewal_failed")
                        return

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login",
                                "--slot", str(slot), "--api-url", API_URL], cwd=ROOT,
                               env=test_account_environment(), capture_output=True,
                               text=True, check=False, timeout=180)
        if login.returncode:
            raise ProofError("disposable_account_bootstrap_failed")
        project = command(cli, ["projects", "create", f"Code Run proof {uuid4().hex[:10]}",
                               "--write-policy", "always_ask", "--personal"])
        project_id = (project.get("project") or {}).get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ProofError("disposable_project_missing")
        receipt["project_id"] = project_id
        nonce = uuid4().hex
        for case in prompts(nonce):
            if errors:
                raise ProofError("lease_renewal_failed")
            directory = recording / case["label"]
            directory.mkdir(mode=0o700)
            slug = f"code-run-proof-{uuid4().hex}-{case['label']}"
            entry = {"label": case["label"], "slug": slug, "status": "failed", "proof_dir": str(directory)}
            receipt["cases"].append(entry)
            input_path = directory / "input.json"
            write_receipt(input_path, {"cli": cli, "sdk_module": str(sdk_module), "project_id": project_id,
                                      "case": case, "slug": slug, "nonce": nonce, "proof": fnv1a(nonce),
                                      "timeout_seconds": args.timeout_seconds})
            print(f"Recording actual CLI flow: {case['label']}", flush=True)
            capture_dir = directory / "terminal"
            capture_timeout = args.timeout_seconds + 600
            captured = subprocess.run([sys.executable, str(ROOT / "scripts/cli_video_capture.py"),
                                      "--output-dir", str(capture_dir), "--target-environment", API_URL,
                                      "--display-number", str(180 + slot), "--timeout-seconds", str(capture_timeout),
                                      "--no-response-media", "--", sys.executable, str(Path(__file__).resolve()),
                                      "--flow-input", str(input_path)], cwd=ROOT, capture_output=True,
                                     text=True, check=False, timeout=capture_timeout+45)
            if (directory / "result.json").exists():
                entry.update(json.loads((directory / "result.json").read_text()))
            entry["recording_status"] = "captured" if (capture_dir / "raw-terminal.mp4").exists() else "failed"
            entry["terminal_recording"] = str(capture_dir / "raw-terminal.mp4")
            entry["terminal_manifest"] = str(capture_dir / "manifest.json")
            if captured.returncode or entry["recording_status"] != "captured":
                entry["status"] = "failed"
                entry.setdefault("error_code", "terminal_capture_or_flow_failed")
            write_receipt(receipt_path, receipt)
            print(f"{case['label']}: {entry['status']}", flush=True)
        receipt["status"] = "passed" if all(case["status"] == "passed" for case in receipt["cases"]) else "failed"
        if errors:
            raise ProofError("lease_renewal_failed")
        require_runtime_revision(args.revision)
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
    finally:
        for case in receipt["cases"]:
            try:
                chat_id = case.get("chat_id")
                if not chat_id:
                    # Unique invocation-owned slug only; never delete by 'last',
                    # title resemblance or pre-existing account inventory.
                    shown = command(cli, ["chats", "show", case["slug"], "--personal"])
                    chat_id = shown.get("chat", {}).get("id")
                if not chat_id:
                    raise ProofError("owned_chat_cleanup_id_missing")
                command(cli, ["chats", "delete", chat_id, "--yes", "--personal"])
                receipt["cleanup"][case["label"]] = "deleted"
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"][case["label"]] = "failed"
                receipt["status"] = "failed"
        if project_id:
            try:
                command(cli, ["projects", "delete", project_id, "--confirm", project_id, "--personal"])
                receipt["cleanup"]["project"] = "deleted"
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["project"] = "failed"
                receipt["status"] = "failed"
        stop.set()
        if heartbeat:
            heartbeat.join(timeout=2)
        for lease_id, *_ in reversed(leases):
            try:
                sessions.release_test_resource_lease(lease_id)
            except RuntimeError:
                receipt["cleanup"]["lease"] = "failed"
                receipt["status"] = "failed"
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_receipt(receipt_path, receipt)
        if created_state:
            shutil.rmtree(state)
        os.umask(old_umask)
        print(f"Code Run real proof {receipt['status']}; private receipt: {receipt_path}", flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--flow-input":
        raise SystemExit(flow(Path(sys.argv[2])))
    raise SystemExit(main())
