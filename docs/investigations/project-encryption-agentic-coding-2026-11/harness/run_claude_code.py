"""Claude Code baseline: same seed repo and task prompts, local file tools.

Each task gets a fresh git copy of the seed. Every stream-json event is
timestamped on arrival so tool-call gaps can be measured.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_openmates import TASKS, materialize_seed  # noqa: E402 - import after the sys.path setup above

OUT = Path(sys.argv[1])
MODEL = sys.argv[2] if len(sys.argv) > 2 else "sonnet"
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 1
OUT.mkdir(parents=True, exist_ok=True)
rows = []
for run in range(RUNS):
    for label, prompt in TASKS:
        repo = OUT / f"repo-run{run}-{label}"
        shutil.rmtree(repo, ignore_errors=True)
        materialize_seed(repo)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=bench@example.org", "-c", "user.name=bench", "commit", "-qm", "seed"],
                       cwd=repo, check=True)
        text = prompt.replace("in the cloud Project ", "").replace("the Project files", "the files")
        cmd = ["claude", "-p", text, "--model", MODEL, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits",
               "--allowedTools", "Read", "Edit", "Write", "Grep", "Glob", "Bash(python -m unittest*)"]
        start = time.time()
        events = []
        proc = subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        for line in proc.stdout:
            try:
                events.append({"t": time.time() - start, "e": json.loads(line)})
            except json.JSONDecodeError:
                pass
        proc.wait()
        end = time.time()
        tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=repo,
                               capture_output=True, text=True)
        tool_uses = [ev for ev in events if ev["e"].get("type") == "assistant"
                     for c in ev["e"].get("message", {}).get("content", []) if c.get("type") == "tool_use"]
        result = next((ev["e"] for ev in events if ev["e"].get("type") == "result"), {})
        row = {"run": run, "task": label, "model": MODEL, "wall_s": round(end - start, 2),
               "tool_calls": len(tool_uses), "num_turns": result.get("num_turns"),
               "duration_api_ms": result.get("duration_api_ms"), "duration_ms": result.get("duration_ms"),
               "tests_exit": tests.returncode, "exit": proc.returncode}
        (OUT / f"run{run}-{label}.events.json").write_text(json.dumps(events))
        subprocess.run(["git", "diff"], cwd=repo, stdout=open(OUT / f"run{run}-{label}.diff", "w"))
        rows.append(row)
        print(json.dumps(row), flush=True)
        (OUT / "timings.json").write_text(json.dumps(rows, indent=1))
