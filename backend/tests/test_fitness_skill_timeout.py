"""Fitness multi-date discovery has a finite assistant envelope."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.skill_executor import (
    DEFAULT_SKILL_TIMEOUT, execute_skill_with_multiple_requests, get_skill_timeout,
)


@pytest.mark.parametrize('arguments', [{}, {'days': 3}, {'requests': [{'days': 3}] * 3}])
def test_class_search_gets_sixty_seconds(arguments):
    assert get_skill_timeout('fitness', 'search_classes', arguments) == 60.0


def test_other_fitness_skills_keep_default_timeout():
    assert get_skill_timeout('fitness', 'search_locations', {}) == DEFAULT_SKILL_TIMEOUT == 20.0


@pytest.mark.asyncio
@pytest.mark.parametrize('timeout', [.5, 90.0])
async def test_explicit_caller_deadlines_are_preserved(monkeypatch, timeout):
    from backend.apps.ai.processing import skill_executor

    dispatch = AsyncMock(return_value={'results': []})
    monkeypatch.setattr(skill_executor, 'execute_skill', dispatch)
    result = await execute_skill_with_multiple_requests(
        'fitness', 'search_classes', {'requests': [{'days': 3}] * 3}, timeout=timeout)
    assert result == [{'results': []}]
    assert dispatch.await_args.args[3] == timeout
