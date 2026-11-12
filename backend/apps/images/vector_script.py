"""Sandbox execution of SVG generator scripts for the images-generate skill.

The ``script`` vector engine has the author model write a deterministic Python
module with ``build_svg()``. This module runs it once in an isolated E2B
sandbox without internet access and returns the SVG text. The model's code
never runs in a worker process.

Sandbox time is billed like Code Run: per started minute of run time.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any, Optional

# The Code Run price per started sandbox minute, shared with every metered sandbox skill.
from backend.shared.python_utils.metered_author_billing import (
    SANDBOX_CREDITS_PER_STARTED_MINUTE as SCRIPT_CREDITS_PER_STARTED_MINUTE,
    sandbox_run_credits as script_run_credits,
)

# Re-exported for the callers that price sandbox runs through this module.
__all__ = ["SCRIPT_CREDITS_PER_STARTED_MINUTE", "SCRIPT_RUN_LIMIT_SECONDS", "script_run_credits"]

SCRIPT_RUN_LIMIT_SECONDS = 60
MAX_ERROR_CHARS = 1500

_MODULE_PATH = "generate.py"
_RUNNER_PATH = "main.py"
_OUTPUT_NAME = "drawing.txt"
# The runner stores the SVG as .txt because the sandbox only exports allow-listed artifact types.
_RUNNER = f'''import os
import generate

svg = generate.build_svg()
if not isinstance(svg, str):
    raise TypeError("build_svg() must return the SVG document as a string")
os.makedirs("outputs", exist_ok=True)
with open(os.path.join("outputs", "{_OUTPUT_NAME}"), "w", encoding="utf-8") as handle:
    handle.write(svg)
'''


@dataclass(frozen=True)
class ScriptRun:
    """Outcome of one sandbox run: the SVG text or the error, and the billable run time."""

    svg: Optional[str]
    seconds: float
    error: Optional[str] = None


async def run_generator_script(code: str, *, secrets_manager: Any, task_id: str) -> ScriptRun:
    """Execute a generator module in the sandbox and return what ``build_svg()`` produced."""
    from backend.shared.providers.e2b_code_runner import (
        CodeRunCancelled,
        CodeRunFile,
        get_e2b_api_key_async,
        run_code_in_e2b,
    )

    api_key = await get_e2b_api_key_async(secrets_manager)
    errors: list[str] = []
    started: list[float] = []

    def on_output(kind: str, text: str) -> None:
        if kind == "status" and text.startswith("Running"):
            started.append(time.monotonic())
        elif kind == "stderr":
            errors.append(text)

    def over_limit() -> bool:
        return bool(started) and time.monotonic() - started[0] > SCRIPT_RUN_LIMIT_SECONDS

    files = [
        CodeRunFile(path=_MODULE_PATH, language="python", content=code),
        CodeRunFile(path=_RUNNER_PATH, language="python", content=_RUNNER, is_target=True),
    ]
    try:
        run = await asyncio.to_thread(
            run_code_in_e2b, files, _RUNNER_PATH, on_output, api_key, None, over_limit, False,
        )
    except CodeRunCancelled:
        seconds = time.monotonic() - started[0] if started else 0.0
        return ScriptRun(None, seconds, f"the script ran longer than {SCRIPT_RUN_LIMIT_SECONDS} seconds")

    error_text = "".join(errors).strip()[-MAX_ERROR_CHARS:]
    if run.exit_code != 0:
        return ScriptRun(None, run.duration_seconds, error_text or f"exit code {run.exit_code}")
    for artifact in run.artifacts or []:
        if str(artifact.get("path", "")).endswith(_OUTPUT_NAME):
            svg = base64.b64decode(str(artifact["content_base64"])).decode("utf-8")
            return ScriptRun(svg, run.duration_seconds)
    return ScriptRun(None, run.duration_seconds, error_text or "build_svg() produced no output (or more than 5 MB)")
