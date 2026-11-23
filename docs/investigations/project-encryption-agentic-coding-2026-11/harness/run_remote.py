"""Dev-only agentic coding benchmark on a connected machine (remote-access source).

A throwaway account's npm CLI attaches a local copy of the seed repo with
`openmates remote-access` (foreground, commands enabled when confinement works),
then the same three task prompts run against that Project. Optional
BENCH_LARGE=N adds N synthetic filler modules to test search on a large repo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_openmates import API_URL, TASKS, cli, dev_test_account, materialize_seed, sessions  # noqa: E402 - import after the sys.path setup above

SESSION = os.environ["BENCH_SESSION"]
OUT = Path(os.environ["BENCH_OUT"])
LARGE = int(os.environ.get("BENCH_LARGE", "0"))
COMMANDS = os.environ.get("BENCH_COMMANDS", "1") == "1"

LARGE_TASK = ("large_repo_search", "Which function in this Project's files raises the error message "
              "'checksum mismatch for ledger'? Name the file and line. Do not run any commands.")


def make_repo(root: Path) -> None:
    materialize_seed(root)
    for index in range(LARGE):
        folder = root / "filler" / f"pkg{index // 100:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"def helper_{index}_{n}(value):\n    return value * {n} + {index}\n" for n in range(12))
        if index == LARGE - 7:
            body += "\n\ndef verify_ledger(rows):\n    raise ValueError('checksum mismatch for ledger')\n"
        (folder / f"module_{index:04d}.py").write_text(body)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=bench@example.org", "-c", "user.name=bench", "commit", "-qm", "seed"],
                   cwd=root, check=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    state = Path(f"/tmp/om-remote-state-{os.getpid()}")
    state.mkdir(mode=0o700)
    root = Path(f"/tmp/om-remote-repo-{os.getpid()}") / "textstats"
    root.parent.mkdir(mode=0o700)
    make_repo(root)
    account = dev_test_account.acquire_real_test_account(
        "enc-bench-remote", SESSION, "encryption-benchmark-remote", stack_timeout=300, prefer_throwaway=True)
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
    host = None
    try:
        creds = {k: v for k, v in account.environment.items() if k.startswith("OPENMATES_TEST_ACCOUNT_")}
        dev_test_account.login_state(creds, state)
        env = {**os.environ, "OPENMATES_STATE_DIR": str(state), "OPENMATES_API_URL": API_URL, "OPENMATES_PROFILE": ""}
        args = ["openmates", "remote-access", "--personal", "--path", str(root), "--project", "new",
                "--write-policy", "apply_and_show", "--json", "--api-url", API_URL]
        if COMMANDS:
            args.append("--enable-commands")
        log = open(OUT / "remote-access.log", "w")
        host = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        project_id = None
        deadline = time.time() + 120
        while time.time() < deadline and project_id is None:
            time.sleep(2)
            text = (OUT / "remote-access.log").read_text()
            if '"connected"' in text and '"projectId"' in text:
                project_id = text.split('"projectId": "')[1].split('"')[0]
        if project_id:
            time.sleep(3)
            code2, out2, err2, _, _ = cli(state, ["projects", "sources", "list", project_id, "--personal", "--json"], 60)
            (OUT / "sources.json").write_text(out2 + err2)
        if project_id is None:
            raise RuntimeError("remote source never came online; see remote-access.log")
        only = [t for t in os.environ.get("BENCH_TASKS", "").split(",") if t]
        tasks = [LARGE_TASK] if LARGE else [t for t in TASKS if not only or t[0] in only]
        if not COMMANDS:
            tasks = [t for t in tasks if t[0] != "test_fix_loop"]
        for label, prompt in tasks:
            prompt = prompt.replace("in the cloud Project", "on my connected machine")
            code, out, err, start, end = cli(state, [
                "chats", "new", "@Gemini-3.8-Flash " + prompt, "--project", project_id, "--personal",
                "--auto-approve", "--no-pii-detection", "--json", "--response-timeout-seconds", "900"], 960)
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                data = {}
            row = {"mode": "remote", "large": LARGE, "task": label, "project_id": project_id,
                   "chat_id": data.get("chatId"), "status": data.get("status"), "exit": code, "start": start,
                   "end": end, "wall_s": round(end - start, 2), "stderr_tail": err[-400:]}
            (OUT / f"{label}.json").write_text(json.dumps({"row": row, "response": data}, indent=1))
            results.append(row)
            print(json.dumps(row), flush=True)
            (OUT / "timings.json").write_text(json.dumps(results, indent=1))
        subprocess.run(["git", "diff", "--stat"], cwd=root, stdout=open(OUT / "repo.diffstat", "w"))
        tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=root,
                               capture_output=True, text=True)
        (OUT / "final_tests.txt").write_text(f"exit={tests.returncode}\n{tests.stderr[-2000:]}")
    finally:
        if host is not None:
            host.terminate()
            try:
                host.wait(20)
            except subprocess.TimeoutExpired:
                host.kill()
        stop.set()
        receipt = dev_test_account.finish_real_test_account(account)
        (OUT / "account_receipt.json").write_text(json.dumps(receipt, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
