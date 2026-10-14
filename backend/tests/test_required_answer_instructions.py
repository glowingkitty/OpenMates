"""Use shipped instruction fixtures to verify cache repair and fail-closed loads."""
# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.utils import instruction_loader as loader


# contract-test: supporting surface=rest_api assertions=ai-model-routing.instructions.required-safety
@pytest.mark.parametrize("key", loader.REQUIRED_ANSWER_INSTRUCTIONS)
@pytest.mark.parametrize("value", [None, "", " \n", {}, []])
def test_missing_required_instruction_rejects_even_nonempty_bundle(key, value):
    bundle = loader.load_base_instructions()
    bundle[key] = value
    with pytest.raises(RuntimeError, match=key):
        loader.validate_required_answer_instructions(bundle)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.instructions.required-safety
def test_startup_disk_load_rejects_missing_required_prose(monkeypatch):
    real_prose = loader._load_markdown_instructions(loader.INSTRUCTIONS_MD_DIR)
    real_prose.pop("base_privacy_instruction")
    monkeypatch.setattr(loader, "_load_markdown_instructions", lambda _path: real_prose)
    with pytest.raises(RuntimeError, match="base_privacy_instruction"):
        loader.load_base_instructions()


# contract-test: supporting surface=rest_api assertions=ai-model-routing.instructions.required-safety
@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [None, {"base_ethics_instruction": "old partial cache"}])
async def test_cached_bundle_missing_required_prose_reloads_real_complete_disk_bundle(cached):
    cache = SimpleNamespace(get_base_instructions=AsyncMock(return_value=cached),
                            set_base_instructions=AsyncMock())
    bundle = await loader.load_validated_base_instructions(cache)
    real = loader.load_base_instructions()
    assert bundle == real
    cache.set_base_instructions.assert_awaited_once_with(real)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.instructions.required-safety
@pytest.mark.asyncio
async def test_valid_cache_needs_no_disk_reload(monkeypatch):
    bundle = loader.load_base_instructions()
    cache = SimpleNamespace(get_base_instructions=AsyncMock(return_value=bundle),
                            set_base_instructions=AsyncMock())
    monkeypatch.setattr(loader, "load_base_instructions", lambda: pytest.fail("unexpected disk read"))
    assert await loader.load_validated_base_instructions(cache) is bundle
    cache.set_base_instructions.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=ai-model-routing.instructions.required-safety
@pytest.mark.asyncio
async def test_invalid_cache_and_missing_disk_section_fail_without_recaching(monkeypatch):
    bundle = loader.load_base_instructions()
    bundle.pop("base_ethics_instruction")
    cache = SimpleNamespace(get_base_instructions=AsyncMock(return_value=bundle),
                            set_base_instructions=AsyncMock())
    monkeypatch.setattr(loader, "load_base_instructions", lambda: bundle)
    with pytest.raises(RuntimeError, match="base_ethics_instruction"):
        await loader.load_validated_base_instructions(cache)
    cache.set_base_instructions.assert_not_awaited()
