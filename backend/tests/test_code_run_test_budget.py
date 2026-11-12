# backend/tests/test_code_run_test_budget.py
#
# Per-turn budget of automatic E2B test runs (agentic-tests-and-git-sync T1).

from __future__ import annotations

import pytest

from backend.apps.code.skills import run_code_skill as skill


class _Cache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None) -> bool:
        self.values[key] = value
        return True


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
@pytest.mark.asyncio
async def test_eleventh_test_run_in_a_turn_asks_the_user() -> None:
    cache = _Cache()
    for _ in range(skill.CODE_RUN_ASSISTANT_MAX_TEST_RUNS_PER_TURN):
        ok, _reason = await skill._authorize_assistant_test_run(cache, chat_id="c", message_id="m")
        assert ok is True
    ok, reason = await skill._authorize_assistant_test_run(cache, chat_id="c", message_id="m")
    assert ok is False
    assert "Ask the user" in reason


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
@pytest.mark.asyncio
async def test_budget_is_per_turn_and_separate_from_code_rerun_limit() -> None:
    cache = _Cache()
    assert skill.CODE_RUN_ASSISTANT_MAX_TEST_RUNS_PER_TURN == 10
    for _ in range(10):
        await skill._authorize_assistant_test_run(cache, chat_id="c", message_id="m1")
    ok, _ = await skill._authorize_assistant_test_run(cache, chat_id="c", message_id="m2")
    assert ok is True
