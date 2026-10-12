#!/usr/bin/env python3
"""Real PTY Return-to-painted-Mate timing. Prepare by default; --execute uses real AI.

Uses the built product TUI, never the SDK send path. Run only after the task's dev
runtime lease/deploy and with an explicitly supplied authenticated test state.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time

PROMPTS = {"spain": "What’s the capital of Spain?", "berlin": "Find AI events in Berlin"}

def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)

def events_at(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # Last append may still be in flight.
    return result

def run_case(args: argparse.Namespace, case: str, temperature: str, directory: Path) -> dict:
    events_path = directory / "paint-events.jsonl"
    if events_path.exists():
        raise RuntimeError(f"Refusing to overwrite evidence: {events_path}")
    env = {**os.environ, "OPENMATES_STATE_DIR": str(args.state_dir.resolve()),
           "OPENMATES_API_URL": args.api_url, "OPENMATES_TUI_LATENCY_EVENTS": str(events_path),
           "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 38, 120, 0, 0))
    child = subprocess.Popen(["node", str(args.cli.resolve())], stdin=slave, stdout=slave,
                             stderr=slave, env=env, start_new_session=True)
    os.close(slave)
    transcript = directory / "terminal.ansi"
    ready_at = sent_at = None
    tail = b""
    started = time.monotonic()
    result = {"case": case, "temperature": temperature, "prompt": PROMPTS[case],
              "measurement": "actual_product_tui_pty_keypress_to_render", "expected_model": args.expected_model,
              "expected_thinking_level": "LOW (verify server logs; harness does not override preferences)",
              "warm_idle_seconds": args.warm_idle_seconds if temperature == "warm" else 0}
    try:
        with transcript.open("wb") as output:
            transcript.chmod(0o600)
            while time.monotonic() - started < args.timeout_seconds:
                readable, _, _ = select.select([master], [], [], 0.05)
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.write(chunk)
                    tail = (tail + chunk)[-250_000:]
                if ready_at is None and b"Ask anything" in tail:
                    ready_at = time.monotonic()
                idle = args.warm_idle_seconds if temperature == "warm" else 0
                if ready_at is not None and sent_at is None and time.monotonic() - ready_at >= idle:
                    os.write(master, PROMPTS[case].encode())
                    # Give the actual terminal input handler time to paint the draft.
                    time.sleep(0.15)
                    os.write(master, b"\r")
                    sent_at = time.time()
                events = events_at(events_path)
                if any(event.get("milestone") == "final" for event in events):
                    break
                if child.poll() is not None:
                    break
        events = events_at(events_path)
        result["enter_wall_time_ms"] = round(sent_at * 1000) if sent_at else None
        result["milestones"] = events
        by_name = {event["milestone"]: event for event in events}
        result["selected_mate_within_1500ms"] = by_name.get("selected_mate", {}).get("elapsedMs", float("inf")) <= 1500
        result["authored_within_3000ms"] = by_name.get("authored_first", {}).get("elapsedMs", float("inf")) <= 3000 if case == "spain" else None
        painted_models = [event.get("modelName") for event in events if event.get("modelName")]
        result["painted_models"] = sorted(set(painted_models))
        def normalize(value: str) -> str:
            return re.sub(r"[^a-z0-9]", "", value.lower())
        result["painted_model_matches"] = any(normalize(args.expected_model) in normalize(model) for model in painted_models)
        result["actual_provider_verification"] = "pending_server_log_correlation"
        result["completed"] = "final" in by_name
        result["timing_targets_met"] = result["selected_mate_within_1500ms"] and result["authored_within_3000ms"] is not False
        result["status"] = ("timing_targets_met" if result["timing_targets_met"] else "timing_target_missed") if result["completed"] else "incomplete"
    finally:
        try:
            os.write(master, b"\x03")
            child.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)
        os.close(master)
    write_json(directory / "result.json", result)
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, default=Path("frontend/packages/openmates-cli/dist/cli.js"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--warm-idle-seconds", type=float, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=150)
    parser.add_argument("--expected-model", default="gemini-3.8-flash")
    parser.add_argument("--case", choices=["all", *PROMPTS], default="all")
    parser.add_argument("--temperature", choices=["all", "cold", "warm"], default="all")
    parser.add_argument("--execute", action="store_true", help="Execute real AI after runtime authorization")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    for case in PROMPTS if args.case == "all" else [args.case]:
        for temperature in ["cold", "warm"] if args.temperature == "all" else [args.temperature]:
            directory = args.output_dir / f"{case}-{temperature}"
            directory.mkdir(exist_ok=True, mode=0o700)
            # Optional minimal graphical capture using the repository's real-PTY recorder.
            steps = [{"name": "composer-ready", "wait_for": "Ask anything", "hold_ms": 1}]
            if temperature == "warm":
                for index in range(4):
                    steps.append({"name": f"warm-idle-{index}", "hold_ms": 5000})
            steps.extend([{"name": "draft", "text": PROMPTS[case], "hold_ms": 150},
                          {"name": "send", "key": "Return", "hold_ms": 1}])
            if case == "spain":
                steps.append({"name": "authored-answer", "wait_for": "Madrid", "wait_timeout_ms": 30000, "hold_ms": 2000})
            else:
                for index in range(12):
                    steps.append({"name": f"tool-and-answer-{index}", "hold_ms": 5000})
            steps.append({"name": "exit", "key": "ctrl+c", "hold_ms": 1})
            write_json(directory / "capture-input.json", {"steps": steps})
            if args.execute:
                results.append(run_case(args, case, temperature, directory))
    write_json(args.output_dir / "summary.json", {"executed": args.execute, "results": results,
        "cold_definition": "Fresh TUI process; sends on first composer paint; does not delete account caches.",
        "warm_definition": "Fresh TUI process with idle startup preparation before Return.",
        "graphical_capture": "Use scripts/cli_video_capture.py --input-plan CASE/capture-input.json --no-response-media with the same environment and built CLI; set OPENMATES_TUI_LATENCY_EVENTS to a fresh per-capture path."})
    print(str(args.output_dir / "summary.json"))
    return 0 if not args.execute or all(result["completed"] and result["timing_targets_met"] and result["painted_model_matches"] for result in results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
