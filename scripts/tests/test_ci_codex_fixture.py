# contract-test-file: tooling
"""Keep CI Codex metadata setup separate from user daemons and inference.

The actual daemon/thread protocol is verified on a GitHub-hosted runner.
Local checks ensure the entrypoint refuses non-runner execution and its RPC
allowlist cannot grow into prompt or turn execution by accident.
See docs/architecture/isolated-github-tests.md.
"""
from pathlib import Path
import os
import re
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "ci_codex_fixture.mjs"


def test_fixture_rejects_local_execution_before_starting_runtime():
    env = {key: value for key, value in os.environ.items() if key not in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT")}
    result = subprocess.run(["node", str(SCRIPT), "start"], env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert "requires an isolated GitHub-hosted runner" in result.stderr


def test_metadata_protocol_cannot_send_turns_or_prompts():
    source = SCRIPT.read_text()
    allowed = re.search(r"const methods = new Set\(\[([^]]+)\]\)", source).group(1)
    assert set(re.findall(r"'([^']+)'", allowed)) == {"initialize", "initialized", "thread/start", "thread/read"}
    assert "process.env.OPENAI_API_KEY" not in source
    assert "...process.env" not in source
