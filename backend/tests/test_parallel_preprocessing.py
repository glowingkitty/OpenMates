"""Parallel URL safeguard and per-turn credit reuse in preprocessing."""

import asyncio
import importlib.util
import pathlib
import sys
import time

import pytest

_PATH = pathlib.Path(__file__).parents[1] / "apps/ai/processing/parallel_url_safeguard.py"
_spec = importlib.util.spec_from_file_location("parallel_url_safeguard", _PATH)
module = importlib.util.module_from_spec(_spec)
sys.modules["parallel_url_safeguard"] = module
_spec.loader.exec_module(module)
sanitize_texts_parallel = module.sanitize_texts_parallel


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.early-resolution
async def test_parallel_checks_keep_order_and_per_message_verdicts():
    async def verdict(text: str) -> str:
        await asyncio.sleep(0.05 if text == "slow" else 0)
        return text.replace("bad.example", "")

    result = await sanitize_texts_parallel(["slow", "a bad.example b", "c"], verdict)
    assert result == ["slow", "a  b", "c"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.early-resolution
async def test_parallel_checks_are_concurrent_and_bounded():
    active = peak = 0

    async def one(text: str) -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return text

    started = time.monotonic()
    await sanitize_texts_parallel([str(i) for i in range(8)], one, concurrency=4)
    assert peak == 4
    assert time.monotonic() - started < 0.3  # serial would be 0.4 s


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.early-resolution
async def test_first_failure_propagates_and_cancels_rest():
    cancelled = []

    async def one(text: str) -> str:
        if text == "boom":
            raise RuntimeError("safeguard down")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(text)
            raise
        return text

    with pytest.raises(RuntimeError, match="safeguard down"):
        await sanitize_texts_parallel(["a", "boom", "b"], one)
    assert sorted(cancelled) == ["a", "b"]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.early-resolution
def test_stage_one_credit_admission_freshness():
    pytest.importorskip("redis")
    from backend.apps.ai.processing.preprocessor import stage_one_credit_admission_fresh as fresh

    assert fresh({"credit_admitted_at": time.time()})
    assert not fresh({"credit_admitted_at": time.time() - 120})
    assert not fresh({"credit_admitted_at": time.time() + 120})
    assert not fresh({"credit_admitted_at": True})
    assert not fresh({})
    assert not fresh(None)
