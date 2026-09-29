"""Dev-only, real-inference E2E check for recent AI model answers.

Run with an isolated authenticated OPENMATES_STATE_DIR and a disposable
OPENMATES_AI_MODEL_TEST_PROJECT. The optional ``--mode plans`` also checks
current subscription sourcing. This check intentionally does not run in CI.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import argparse


PLAN_PROMPT = (
    "research and compare how much usage people get from their Claude vs codex "
    "subscription currently. openai just announced that they cut the usage in "
    "half for the 200$ plan. which makes me wonder if anthropic is doing any "
    "better or is similar bad."
)
MODEL_PROMPT = (
    "Using only the OpenMates model catalogue, name recent OpenAI, Anthropic, "
    "and Google language models and recent image, video, and audio models. "
    "Include release dates and one core capability each. Do not search the web."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("plans", "models"), default="models")
    args = parser.parse_args()
    state_dir = os.environ["OPENMATES_STATE_DIR"]
    project = os.environ["OPENMATES_AI_MODEL_TEST_PROJECT"]
    if not os.path.isdir(state_dir):
        raise SystemExit("OPENMATES_STATE_DIR must be a private CLI state directory")
    result = subprocess.run(
        ["openmates", "chats", "new", MODEL_PROMPT if args.mode == "models" else PLAN_PROMPT,
         "--project", project, "--auto-approve", "--json"],
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
    if args.mode == "models":
        for name in ("GPT-6", "Claude Opus 5.5", "GPT Image 2", "Veo 3.1", "Voxtral Mini"):
            if name not in answer:
                raise AssertionError(f"Missing catalogued recent model: {name}")
        if "release date unrecorded" not in answer.lower():
            raise AssertionError("Undated audio models should not receive invented release dates")
        print(answer)
        return
    required = (r"\bcodex\b", r"\bclaude code\b", r"\bmax\s*20[x×](?:\s|[.,;)]|$)")
    for pattern in required:
        if not re.search(pattern, answer, re.IGNORECASE):
            raise AssertionError(f"Missing current comparison concept: {pattern}")
    for obsolete in (r"\bGPT-4o\b", r"\bo1 Pro\b", r"\bClaude 3\.7\b"):
        if re.search(obsolete, answer, re.IGNORECASE):
            raise AssertionError(f"Answer centers an obsolete model: {obsolete}")
    if not re.search(r"(?:help\.openai\.com|openai\.com|chatgpt\.com)", answer, re.IGNORECASE):
        raise AssertionError("Current OpenAI usage claims lack an official source")
    if not re.search(r"(?:support\.claude\.com|anthropic\.com|claude\.com)", answer, re.IGNORECASE):
        raise AssertionError("Current Anthropic usage claims lack an official source")
    print(answer)


if __name__ == "__main__":
    main()
