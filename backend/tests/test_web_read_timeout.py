"""Public reading retains bounded fetch and safety work without changing overrides."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import skill_executor


def test_read_envelope_includes_policy_fetch_and_output_scan():
    assert skill_executor.get_skill_timeout("web", "read", {"requests": [{"url": "https://example.com"}]}) == 75.0
    assert skill_executor.get_skill_timeout("web", "search", {}) == 20.0


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_timeout,expected", [(None, 75.0), (0.5, 0.5)])
async def test_read_dispatch_preserves_explicit_timeout(monkeypatch, explicit_timeout, expected):
    dispatch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(skill_executor, "execute_skill", dispatch)
    arguments = {"requests": [{"url": "https://example.com"}]}
    # The assistant selects its envelope before calling this shared dispatcher.
    timeout = skill_executor.get_skill_timeout("web", "read", arguments) if explicit_timeout is None else explicit_timeout
    await skill_executor.execute_skill_with_multiple_requests(
        "web", "read", arguments, timeout=timeout,
    )
    assert dispatch.await_args.args[3] == expected
