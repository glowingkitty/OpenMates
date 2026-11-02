"""Paired benchmark orchestration: warmup, ABAB samples, JSON + Markdown report."""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import flows as F
from .meter import Meter
from .stats import ARMS, flow_summary, markdown_table, paired_order

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Runner:
    def __init__(self, meter: Meter, arms: dict[str, F.Arm], *, samples: int, warmup: int,
                 timeout: float, message: str, followup: str, app_skill: str,
                 chat_ids: dict[str, str | None], create_chat: bool = False,
                 keep_output: Path | None = None, log=None,
                 arm_messages: dict[str, str] | None = None, arm_followups: dict[str, str] | None = None,
                 expect_model: str | None = None):
        self.meter = meter
        self.arms = arms
        self.samples = samples
        self.warmup = warmup
        self.timeout = timeout
        self.message = message
        self.followup = followup
        # Per-arm overrides when the CLIs need different input for the same wire request
        # (e.g. TS resolves `@Gemini-3.8-Flash`; Rust needs `@ai-model:gemini-3.8-flash`).
        self.arm_messages = {arm: text for arm, text in (arm_messages or {}).items() if text}
        self.arm_followups = {arm: text for arm, text in (arm_followups or {}).items() if text}
        self.expect_model = expect_model
        self.app_skill = app_skill
        self.chat_ids = dict(chat_ids)
        self.create_chat = create_chat  # may create chats untimed (inference opt-in only)
        self.keep_output = keep_output
        self.log = log or (lambda text: print(text, file=sys.stderr, flush=True))
        self.scratch = Path(tempfile.mkdtemp(prefix="rust-bench-out-"))
        os.chmod(self.scratch, 0o700)
        self.counter = 0

    def close(self) -> None:
        shutil.rmtree(self.scratch, ignore_errors=True)

    def invoke(self, arm_name: str, args: list[str], label: str) -> tuple[dict, object]:
        """Run one CLI invocation under the meter; returns (metrics, parsed stdout JSON)."""
        arm = self.arms[arm_name]
        self.counter += 1
        base = (self.keep_output or self.scratch) / f"{self.counter:04d}-{arm_name}-{label}"
        out, err = base.with_suffix(".stdout"), base.with_suffix(".stderr")
        metrics = self.meter.run(arm.argv(args), arm.env(), cwd=str(arm.profile), timeout=self.timeout,
                                 stdout_path=out, stderr_path=err)
        parsed = F.parse_json_output(out.read_bytes())
        if not self.keep_output:
            out.unlink(missing_ok=True)
            err.unlink(missing_ok=True)
        return metrics, parsed

    @staticmethod
    def verdict(metrics: dict, parsed) -> str | None:
        if metrics["timedOut"]:
            return "timeout"
        if metrics["exitCode"] != 0:
            return F.error_code(parsed) or f"exit_{metrics['exitCode']}"
        if parsed is None:
            return "non_json_stdout"
        return F.error_code(parsed)

    def check(self, flow: str, metrics: dict, parsed) -> str | None:
        """verdict() plus, for inference flows with --expect-model, the answering model."""
        error = self.verdict(metrics, parsed)
        if error is None and self.expect_model and flow in ("send", "follow-up"):
            model = F.answered_model(parsed)
            if model != self.expect_model:
                return f"model_mismatch:{model or 'missing'}"
        return error

    def message_for(self, arm: str) -> str:
        return self.arm_messages.get(arm, self.message)

    def followup_for(self, arm: str) -> str:
        return self.arm_followups.get(arm, self.followup)

    def args_for(self, flow: str, arm: str) -> list[str]:
        return F.flow_args(flow, chat_id=self.chat_ids.get(arm), message=self.message_for(arm),
                           followup=self.followup_for(arm), app_skill=self.app_skill)

    def prepare_flow(self, flow: str) -> str | None:
        """Untimed setup. Returns a skip reason or None."""
        spec = F.FLOWS[flow]
        if not spec.needs_chat:
            return None
        for arm in ARMS:
            if flow == "chats-show" and self.chat_ids.get(arm):
                continue
            if flow == "follow-up":
                # A dedicated chat per arm, created untimed; follow-ups accumulate in it.
                metrics, parsed = self.invoke(arm, F.flow_args("send", message=self.message_for(arm)), "setup")
                error = self.check("send", metrics, parsed)
                chat = F.created_chat_id(parsed) if error is None else None
                if not chat:
                    return f"{arm}: could not create follow-up chat ({error or 'no chat id'})"
                self.chat_ids.setdefault(f"followup:{arm}", chat)
                continue
            metrics, parsed = self.invoke(arm, F.flow_args("chats-list"), "setup")
            chat = F.first_chat_id(parsed) if self.verdict(metrics, parsed) is None else None
            if not chat and self.create_chat:
                metrics, parsed = self.invoke(arm, F.flow_args("send", message=self.message_for(arm)), "setup")
                chat = F.created_chat_id(parsed) if self.check("send", metrics, parsed) is None else None
            if not chat:
                return f"{arm}: no chat available to show (pass --{arm}-chat-id or run with --inference first)"
            self.chat_ids[arm] = chat
        return None

    def flow_argv(self, flow: str, arm: str) -> list[str]:
        if flow == "follow-up":
            return F.flow_args(flow, chat_id=self.chat_ids[f"followup:{arm}"], followup=self.followup_for(arm))
        return self.args_for(flow, arm)

    def run_flow(self, flow: str) -> dict:
        spec = F.FLOWS[flow]
        record = {"name": flow, "semanticArgv": spec.semantic, "needsInference": spec.needs_inference}
        skip = self.prepare_flow(flow)
        if skip:
            self.log(f"[{flow}] skipped: {skip}")
            return {**record, "skipped": skip}
        warmups = []
        for arm in ARMS:
            for _ in range(self.warmup):
                metrics, parsed = self.invoke(arm, self.flow_argv(flow, arm), f"{flow}-warmup")
                error = self.check(flow, metrics, parsed)
                warmups.append({"arm": arm, "ok": error is None, "error": error, "wallMs": metrics["wallMs"]})
        samples = []
        for position, (index, arm) in enumerate(paired_order(self.samples)):
            metrics, parsed = self.invoke(arm, self.flow_argv(flow, arm), flow)
            error = self.check(flow, metrics, parsed)
            samples.append({"index": index, "position": position, "arm": arm, "ok": error is None,
                            "error": error, "metrics": metrics})
            self.log(f"[{flow}] #{index:02d} {arm:<10} wall={metrics['wallMs']:9.1f}ms "
                     f"cpu={metrics['cpuMs']:9.1f}ms peak={metrics['peakMemKiB']:8d}KiB"
                     + (f" ERROR={error}" if error else ""))
        return {**record, "warmup": warmups, "samples": samples, "summary": flow_summary(samples)}

    def preflight(self) -> dict[str, str | None]:
        """Untimed `whoami --json` per arm; returns {arm: error-or-None}.

        Logged-out CLIs still answer some reads (e.g. TS `chats list` shows
        examples), so samples are only meaningful for signed-in profiles.
        """
        problems = {}
        for arm in ARMS:
            metrics, parsed = self.invoke(arm, F.flow_args("whoami"), "preflight")
            problems[arm] = self.verdict(metrics, parsed)
        return problems

    def run(self, selected: list[str]) -> list[dict]:
        return [self.run_flow(flow) for flow in selected]


def cli_version(meter: Meter, arm: F.Arm) -> str | None:
    """Untimed `--version` first line, for the report."""
    path = Path(tempfile.mkdtemp(prefix="rust-bench-version-"))
    try:
        result = meter.run(arm.argv(["--version"]) if arm.name == "typescript" else [*arm.command, "--version"],
                           arm.env(), cwd=str(arm.profile), timeout=60, stdout_path=path / "out")
        text = (path / "out").read_text(errors="replace").strip().splitlines()
        return text[0][:120] if result["exitCode"] == 0 and text else None
    finally:
        shutil.rmtree(path, ignore_errors=True)


def host_info() -> dict:
    return {"system": platform.system(), "machine": platform.machine(), "kernel": platform.release(),
            "logicalCpus": os.cpu_count(), "python": platform.python_version()}


def build_report(*, meter: Meter, arms: dict[str, F.Arm], config: dict, flows: list[dict],
                 started: str, versions: dict) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rust-vs-typescript-cli-benchmark",
        "startedAt": started,
        "finishedAt": now_iso(),
        "host": host_info(),
        "meter": meter.describe(),
        "config": config,
        # Basenames only: absolute build/profile paths are private to the host.
        "arms": {name: {"command": " ".join(Path(part).name for part in arm.command),
                        "version": versions.get(name),
                        "isolation": "own HOME/XDG/TMPDIR/OPENMATES_STATE_DIR under a private profile root; "
                                     "env built from scratch"}
                 for name, arm in arms.items()},
        "flows": flows,
    }


def write_outputs(report: dict, json_path: Path, markdown_path: Path | None) -> str:
    import json

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    table = markdown_table(report)
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(table)
    return table

