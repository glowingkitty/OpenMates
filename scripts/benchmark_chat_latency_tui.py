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
SEQUENCES = {
    "factual": [("spain", "What is the capital of Spain?", "Madrid"),
                ("france-followup", "And France?", "Paris"),
                ("germany-followup", "And Germany?", "Berlin")],
    "shorthand": [("france-shorthand", "capital of france?", "Paris")],
    "events": [("berlin", PROMPTS["berlin"], None),
               ("berlin-followup", "Which of those events are best for meeting AI founders?", None)],
}

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
    turns = SEQUENCES.get(args.sequence, [(case, PROMPTS[case], "Madrid" if case == "spain" else None)])
    turn_index = 0
    event_offset = 0
    turn_results: list[dict] = []
    next_send_at = None
    metadata_grace_started = None
    tail = b""
    started = time.monotonic()
    result = {"case": case, "temperature": temperature, "prompt": PROMPTS[case],
              "measurement": "actual_product_tui_pty_keypress_to_render", "expected_model": args.expected_model,
              "expected_thinking_level": "LOW (verify server logs; harness does not override preferences)",
              "warm_idle_seconds": args.warm_idle_seconds if temperature == "warm" else 0,
              "sequence": args.sequence, "turns": turn_results}
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
                if (ready_at is not None and sent_at is None and turn_index < len(turns)
                        and time.monotonic() - ready_at >= idle
                        and (next_send_at is None or time.monotonic() >= next_send_at)):
                    event_offset = len(events_at(events_path))
                    tail = b""
                    os.write(master, turns[turn_index][1].encode())
                    # Give the actual terminal input handler time to paint the draft.
                    time.sleep(0.15)
                    os.write(master, b"\r")
                    sent_at = time.time()
                events = events_at(events_path)
                current_events = events[event_offset:]
                if sent_at is not None and any(event.get("milestone") == "final" for event in current_events):
                    name, prompt, expected = turns[turn_index]
                    by_turn = {event["milestone"]: event for event in current_events}
                    turn_results.append({"case": name, "prompt": prompt,
                        "enter_wall_time_ms": round(sent_at * 1000), "milestones": current_events,
                        "expected_answer_visible": expected in tail.decode(errors="replace") if expected else None,
                        "selected_mate_within_1500ms": by_turn.get("selected_mate", {}).get("elapsedMs", float("inf")) <= 1500,
                        "authored_within_3000ms": by_turn.get("authored_first", {}).get("elapsedMs", float("inf")) <= 3000 if args.sequence != "events" and case != "berlin" else None,
                        "completed": True})
                    turn_index += 1
                    sent_at = None
                    next_send_at = time.monotonic() + 0.25
                    if turn_index == len(turns):
                        metadata_grace_started = time.monotonic()
                if metadata_grace_started is not None and time.monotonic() - metadata_grace_started >= args.metadata_grace_seconds:
                    break
                if child.poll() is not None:
                    break
        events = events_at(events_path)
        result["enter_wall_time_ms"] = turn_results[0]["enter_wall_time_ms"] if turn_results else round(sent_at * 1000) if sent_at else None
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
        result["simple_no_app_skill_progress"] = "tool_progress" not in by_name if case == "spain" else None
        result["completed"] = len(turn_results) == len(turns)
        if args.sequence:
            result["selected_mate_within_1500ms"] = result["completed"] and all(turn["selected_mate_within_1500ms"] for turn in turn_results)
            result["authored_within_3000ms"] = all(turn["authored_within_3000ms"] is not False for turn in turn_results) if args.sequence != "events" else None
        result["timing_targets_met"] = result["completed"] and result["selected_mate_within_1500ms"] and result["authored_within_3000ms"] is not False
        result["all_expected_answers_visible"] = all(turn["expected_answer_visible"] is not False for turn in turn_results)
        result["single_same_chat"] = len({event.get("chatId") for event in events if event.get("chatId")}) <= 1
        result["late_metadata_observation_seconds"] = args.metadata_grace_seconds
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
    parser.add_argument("--sequence", choices=SEQUENCES, help="Run real same-chat follow-ups without waiting for optional metadata")
    parser.add_argument("--metadata-grace-seconds", type=float, default=7,
                        help="Observe late metadata after readiness; excluded from response latency")
    parser.add_argument("--case", choices=["all", *PROMPTS], default="all")
    parser.add_argument("--temperature", choices=["all", "cold", "warm"], default="all")
    parser.add_argument("--execute", action="store_true", help="Execute real AI after runtime authorization")
    args = parser.parse_args()
    if not 0 <= args.metadata_grace_seconds <= 60:
        parser.error("metadata grace must be between zero and sixty seconds")
    if args.timeout_seconds <= 0 or args.warm_idle_seconds < 0:
        parser.error("timeout must be positive and warm idle must be nonnegative")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    cases = ["berlin" if args.sequence == "events" else "spain"] if args.sequence else list(PROMPTS) if args.case == "all" else [args.case]
    for case in cases:
        for temperature in ["cold", "warm"] if args.temperature == "all" else [args.temperature]:
            directory = args.output_dir / f"{case}-{temperature}"
            directory.mkdir(exist_ok=True, mode=0o700)
            # Optional minimal graphical capture using the repository's real-PTY recorder.
            steps = [{"name": "composer-ready", "wait_for": "Ask anything", "hold_ms": 1}]
            if temperature == "warm":
                remaining_ms = round(args.warm_idle_seconds * 1000)
                while remaining_ms > 0:
                    hold_ms = min(5000, remaining_ms)
                    steps.append({"name": f"warm-idle-{len(steps)}", "hold_ms": hold_ms})
                    remaining_ms -= hold_ms
            capture_turns = SEQUENCES.get(args.sequence, [(case, PROMPTS[case], "Madrid" if case == "spain" else None)])
            for name, prompt, expected in capture_turns:
                steps.extend([{"name": f"{name}-draft", "text": prompt, "hold_ms": 150},
                              {"name": f"{name}-send", "key": "Return", "hold_ms": 1}])
                if expected:
                    steps.append({"name": f"{name}-answer", "wait_for": expected, "wait_timeout_ms": 30000, "hold_ms": 2000})
                else:
                    for index in range(12):
                        steps.append({"name": f"{name}-tool-and-answer-{index}", "hold_ms": 5000})
            steps.append({"name": "exit", "key": "ctrl+c", "hold_ms": 1})
            write_json(directory / "capture-input.json", {"steps": steps})
            if args.execute:
                results.append(run_case(args, case, temperature, directory))
    write_json(args.output_dir / "summary.json", {"executed": args.execute, "results": results,
        "cold_definition": "Fresh TUI process; sends on first composer paint; does not delete account caches.",
        "warm_definition": "Fresh TUI process with idle startup preparation before Return.",
        "graphical_capture": "Use scripts/cli_video_capture.py --input-plan CASE/capture-input.json --no-response-media with the same environment and built CLI; set OPENMATES_TUI_LATENCY_EVENTS to a fresh per-capture path."})
    print(str(args.output_dir / "summary.json"))
    return 0 if not args.execute or all(result["completed"] and result["timing_targets_met"] and result["painted_model_matches"] and result["simple_no_app_skill_progress"] is not False for result in results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
