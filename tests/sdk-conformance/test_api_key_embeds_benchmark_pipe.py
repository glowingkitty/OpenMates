"""Pure worker-pipe deadline controls; no SDK, sockets or child process."""

# contract-test-file: tooling
import importlib.util
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location(
    "embed_benchmark_pipe_subject", HERE / "benchmark_api_key_embeds.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def fake_worker(raw):
    reader, writer = os.pipe()
    os.write(writer, raw)
    return SimpleNamespace(stdout=os.fdopen(reader, "rb", buffering=0)), writer


def test_partial_non_newline_output_cannot_escape_absolute_deadline():
    child, writer = fake_worker(b'{"partial":')
    start = time.monotonic()
    try:
        with pytest.raises(AssertionError, match="deadline"):
            benchmark.line(child, timeout=0.03)
        assert time.monotonic() - start < 1
    finally:
        os.close(writer)
        child.stdout.close()


def test_multiple_complete_lines_preserve_pending_bytes():
    child, writer = fake_worker(b'{"ready":true}\n{"done":true}\n')
    try:
        assert benchmark.line(child, timeout=0.1) == {"ready": True}
        assert benchmark.line(child, timeout=0.1) == {"done": True}
    finally:
        os.close(writer)
        child.stdout.close()


def test_eof_cannot_complete_a_partial_json_line():
    child, writer = fake_worker(b'{"partial":')
    os.close(writer)
    try:
        with pytest.raises(AssertionError, match="closed before complete"):
            benchmark.line(child, timeout=0.1)
    finally:
        child.stdout.close()


def test_oversized_unterminated_output_is_rejected():
    child, writer = fake_worker(b"x" * 33)
    try:
        with patch.object(benchmark, "MAX_WORKER_LINE", 32):
            with pytest.raises(AssertionError, match="bounded worker output"):
                benchmark.line(child, timeout=0.1)
    finally:
        os.close(writer)
        child.stdout.close()
