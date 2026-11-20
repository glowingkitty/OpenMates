"""Dev-only agentic coding benchmark: seed a hosted Project, run three coding tasks.

Throwaway dev account (chats backed up, account deleted afterwards), isolated
npm CLI state, real inference with automatic routing. Writes timings.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
import dev_test_account  # noqa: E402 - import after the sys.path setup above
import sessions  # noqa: E402 - import after the sys.path setup above
from project_names import natural_project_name  # noqa: E402 - import after the sys.path setup above

API_URL = "https://api.dev.openmates.org"
HERE = Path(__file__).resolve().parent
SEED = HERE / "seed"
RUNS = int(os.environ.get("BENCH_RUNS", "1"))
SESSION = os.environ["BENCH_SESSION"]
OUT = Path(os.environ["BENCH_OUT"])


def seed_files() -> list[tuple[str, str]]:
    """Seed repo files as (path, content). Stored with a `.seed` suffix so the
    repository's test and Specification gates never treat them as real tests."""
    files = []
    for path in sorted(p for p in SEED.rglob("*.seed") if p.is_file()):
        files.append((path.relative_to(SEED).as_posix()[: -len(".seed")], path.read_text()))
    return files


def materialize_seed(dest: Path) -> None:
    for rel, content in seed_files():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def seed_prompt() -> str:
    parts = ["In this Project, create exactly the following files with exactly this content. "
             "Do not run any commands and do not change the content.\n"]
    for rel, content in seed_files():
        parts.append(f"File `{rel}`:\n```\n{content}```\n")
    return "\n".join(parts)


TASKS = [
    ("small_fix", "count_words('a  b\\nc') returns 2 instead of 3. Find and fix the bug in the Project files. "
                  "Do not run any commands."),
    ("multi_file_feature", "Add a function top_words(text, n=3) to textstats/words.py that returns the n most "
                           "common lower-case words (punctuation .,!? stripped) as (word, count) tuples, most common "
                           "first and ties alphabetical. Export it from textstats/__init__.py, add a 'Top words: ...' "
                           "line to build_report in textstats/report.py, and add unit tests for it in "
                           "tests/test_words.py. Do not run any commands."),
    ("test_fix_loop", "Run the test suite in the cloud Project with the command "
                      "`python -m unittest discover -s tests -t .`, fix whatever fails in the Project files, and "
                      "run it again until it passes."),
]


def cli(state: Path, args: list[str], timeout: int) -> tuple[int, str, str, float, float]:
    env = {**os.environ, "OPENMATES_STATE_DIR": str(state), "OPENMATES_API_URL": API_URL, "OPENMATES_PROFILE": ""}
    for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
        env.pop(key, None)
    start = time.time()
    try:
        proc = subprocess.run(["openmates", *args, "--api-url", API_URL], env=env, capture_output=True, text=True,
                              timeout=timeout, check=False, cwd=str(HERE))
    except subprocess.TimeoutExpired as exc:
        # A hung turn is a result to record, not a reason to abort the remaining tasks.
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return 124, out, f"harness timeout after {timeout} s", start, time.time()
    return proc.returncode, proc.stdout, proc.stderr, start, time.time()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    state = Path(f"/tmp/om-bench-state-{os.getpid()}")
    state.mkdir(mode=0o700)
    account = dev_test_account.acquire_real_test_account(
        "enc-bench", SESSION, "encryption-benchmark", stack_timeout=300, prefer_throwaway=True)
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
            for lease_id, owner, resources, mode in account.leases:
                try:
                    sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)
                except RuntimeError:
                    pass

    threading.Thread(target=renew, daemon=True).start()
    results: list[dict] = []
    try:
        creds = {k: v for k, v in account.environment.items() if k.startswith("OPENMATES_TEST_ACCOUNT_")}
        dev_test_account.login_state(creds, state)
        for run in range(RUNS):
            code, out, err, _, _ = cli(state, ["projects", "create", natural_project_name("Text statistics"),
                                               "--write-policy", "apply_and_show", "--personal", "--json"], 120)
            if code:
                raise RuntimeError(f"project create failed: {err[-300:]}")
            project_id = json.loads(out)["project"]["project_id"]
            only = [t for t in os.environ.get("BENCH_TASKS", "").split(",") if t]
            selected = [t for t in TASKS if not only or t[0] in only]
            for label, prompt in [("seed", seed_prompt()), *selected]:
                code, out, err, start, end = cli(state, [
                    "chats", "new", "@Gemini-3.8-Flash " + prompt, "--project", project_id, "--personal", "--auto-approve",
                    "--no-pii-detection", "--json", "--response-timeout-seconds", "900"], 960)
                try:
                    data = json.loads(out)
                except json.JSONDecodeError:
                    data = {}
                row = {"run": run, "task": label, "project_id": project_id, "chat_id": data.get("chatId"),
                       "status": data.get("status"), "exit": code, "start": start, "end": end,
                       "wall_s": round(end - start, 2), "stderr_tail": err[-400:]}
                (OUT / f"run{run}-{label}.json").write_text(json.dumps({"row": row, "response": data}, indent=1))
                results.append(row)
                print(json.dumps(row), flush=True)
                (OUT / "timings.json").write_text(json.dumps(results, indent=1))
    finally:
        stop.set()
        receipt = dev_test_account.finish_real_test_account(account)
        (OUT / "account_receipt.json").write_text(json.dumps(receipt, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
