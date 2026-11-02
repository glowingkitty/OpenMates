"""Pure performance receipt controls; no SDK, sockets, accounts, or subprocesses."""

# contract-test-file: tooling
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parent


@pytest.mark.parametrize("family", ["docs", "wikipedia"])
@pytest.mark.parametrize(
    "failure", ["low-resolution", "protocol", "adapter", "slowdown", "none"]
)
def test_failed_and_partial_performance_samples_are_retained(family, failure, tmp_path):
    path = ROOT / "runners" / f"sdk-api-key-{family}.py"
    spec = importlib.util.spec_from_file_location("performance_receipt_subject", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {"capabilities": {runner.CAPABILITY: {"vectors": [{"id": "synthetic"}]}}}
        )
    )
    calls = []

    def sample(suite, vector, language, binary, iterations, measurements):
        index = len(calls)
        calls.append(language)
        if failure == "adapter" and index == 2:
            raise AssertionError("synthetic adapter failed before a measurement")
        ticks = (
            1
            if failure == "low-resolution" and index == 2
            else (40 if failure == "slowdown" and language == "rust" else 20)
        )
        observed = {
            "ok": True,
            "value": {"synthetic": index},
            "performance": {"iterations": 1024, "cpuTicks": ticks, "wallMs": 10},
        }
        measurements.append(observed)
        if failure == "protocol" and index == 2:
            raise AssertionError("synthetic protocol failure after measurement")
        return observed

    argv = [
        "runner",
        "--fixture",
        str(fixture),
        "--capability",
        runner.CAPABILITY,
        "--performance",
        "--rust-executable",
        "synthetic-unrun",
    ]
    output = io.StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(runner, "with_peer", sample),
        contextlib.redirect_stdout(output),
    ):
        if failure == "none":
            runner.main()
        else:
            with pytest.raises(AssertionError):
                runner.main()
    receipt = json.loads(output.getvalue())
    assert receipt["status"] == ("passed" if failure == "none" else "failed")
    assert receipt["releaseEligible"] is False
    samples = receipt["samples"]["rust"] + receipt["samples"]["npm"]
    assert len(samples) == (
        10 if failure in ("none", "slowdown") else 2 if failure == "adapter" else 3
    )
    assert {v["value"]["synthetic"] for v in samples} == set(range(len(samples)))
    if failure == "low-resolution":
        assert any(v["performance"]["cpuTicks"] == 1 for v in samples)
        assert receipt["failureStage"] == "insufficient_cpu_resolution"
    elif failure in ("adapter", "protocol"):
        assert receipt["failureStage"] == "adapter_or_protocol"
    elif failure == "slowdown":
        assert receipt["failureStage"] == "rust_slower_than_typescript"
        assert receipt["rustAtLeastAsFastCpu"] is False
