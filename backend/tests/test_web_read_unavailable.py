"""An unavailable reader cannot reconstruct removed connector access."""

import importlib

import pytest
from backend.tests.test_media_ccc_skill import transcript_module  # noqa: F401


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_reader_reports_capability_gap_without_outbound_access(transcript_module):  # noqa: F811
    module = importlib.import_module("backend.apps.web.skills.read_skill")
    skill = module.ReadSkill(app=None, app_id="web", skill_id="read", skill_name="Read", skill_description="Read")
    result = await skill.execute(requests=[{"url": "https://www.youtube.com/watch?v=example"}], secrets_manager=None)
    assert result.results == []
    assert result.provider == ""
    assert result.error == "No supported content reader is configured."
