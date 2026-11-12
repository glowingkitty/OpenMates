"""Tests for the read-outline guard hook."""
# contract-test-file: tooling

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "read-outline-guard.sh"


def run(tool_input, **env):
    return subprocess.run(["bash", str(HOOK)], input=json.dumps({"tool_input": tool_input}),
                          text=True, capture_output=True, check=False,
                          env={**os.environ, **env})


def make(name, lines):
    path = ROOT / "scripts" / "tests" / name
    path.write_text("".join(f"def f{i}():\n    pass\n" for i in range(lines // 2)))
    return path


def test_blocks_big_file_with_outline(tmp_path):
    path = make("_tmp_big_outline.py", 1000)
    try:
        result = run({"file_path": str(path)})
    finally:
        path.unlink()
    assert result.returncode == 2
    assert "has 1000 lines. Read a range (offset/limit)" in result.stderr
    assert "def f0" in result.stderr


def test_passes_with_range_small_and_nonsource():
    path = make("_tmp_small_outline.py", 1000)
    try:
        assert run({"file_path": str(path), "limit": 50}).returncode == 0
        assert run({"file_path": str(path), "offset": 10}).returncode == 0
        assert run({"file_path": str(path)}, OPENMATES_READ_OUTLINE_MIN_LINES="5000").returncode == 0
    finally:
        path.unlink()
    assert run({"file_path": str(ROOT / "scripts" / "nope.py")}).returncode == 0
    assert run({"file_path": str(ROOT / "CLAUDE.md")}).returncode == 0
    assert run({"file_path": "/etc/passwd"}).returncode == 0


def test_fast_on_huge_file():
    start = time.time()
    result = run({"file_path": str(ROOT / "scripts" / "sessions.py")})
    assert result.returncode == 2
    assert time.time() - start < 2
