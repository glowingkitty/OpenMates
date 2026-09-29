"""Dev-only, real-inference E2E check for current coding-subscription answers.

Run with an isolated authenticated OPENMATES_STATE_DIR and a disposable
OPENMATES_AI_MODEL_TEST_PROJECT. This check intentionally does not run in CI.
"""

from __future__ import annotations

import json
import os
import re
import subprocess


PROMPT = (
    "research and compare how much usage people get from their Claude vs codex "
    "subscription currently. openai just announced that they cut the usage in "
    "half for the 200$ plan. which makes me wonder if anthropic is doing any "
    "better or is similar bad."
)


def main() -> None:
    state_dir = os.environ["OPENMATES_STATE_DIR"]
    project = os.environ["OPENMATES_AI_MODEL_TEST_PROJECT"]
    if not os.path.isdir(state_dir):
        raise SystemExit("OPENMATES_STATE_DIR must be a private CLI state directory")
    result = subprocess.run(
        ["openmates", "chats", "new", PROMPT, "--project", project, "--auto-approve", "--json"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=360,
        check=False,
    )
    if result.returncode:
        raise SystemExit(f"Live chat failed (exit {result.returncode}): {result.stderr[-1200:]}")
    payload = json.loads(result.stdout)
    answer = str(payload.get("assistant") or "")
    if not answer:
        raise AssertionError("Live chat returned no assistant answer")
    required = (r"\bcodex\b", r"\bclaude code\b", r"\bmax\s*20x\b")
    for pattern in required:
        if not re.search(pattern, answer, re.IGNORECASE):
            raise AssertionError(f"Missing current comparison concept: {pattern}")
    for obsolete in (r"\bGPT-4o\b", r"\bo1 Pro\b", r"\bClaude 3\.7\b"):
        if re.search(obsolete, answer, re.IGNORECASE):
            raise AssertionError(f"Answer centers an obsolete model: {obsolete}")
    print(answer)


if __name__ == "__main__":
    main()
