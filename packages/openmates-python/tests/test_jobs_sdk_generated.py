"""Generated Python Jobs search facade contract."""

import importlib.util
from pathlib import Path


_generated = Path(__file__).resolve().parents[1] / "openmates/generated/app_skills.py"
_spec = importlib.util.spec_from_file_location("openmates_generated_jobs_test", _generated)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
APP_SKILL_METADATA = _module.APP_SKILL_METADATA
GeneratedAppSkills = _module.GeneratedAppSkills


# contract-test: supporting surface=sdks.pip assertions=app-skills.surface.semantic-parity
def test_jobs_search_metadata_and_native_method() -> None:
    metadata = next(item for item in APP_SKILL_METADATA if (item["app_id"], item["skill_id"]) == ("jobs", "search"))
    request = metadata["schema"]["properties"]["requests"]["items"]["properties"]
    assert request["country"]["default"] == "DE"
    assert request["limit"]["maximum"] == 50
    sdk_group = metadata["output_schema"]["properties"]["results"]["items"]["properties"]
    assert "title" not in sdk_group
    assert sdk_group["results"]["items"]["properties"]["title"]["type"] == "string"
    listing = sdk_group["results"]["items"]["properties"]
    assert listing["remote"]["type"] == ["boolean", "null"]
    assert listing["salary_min"]["type"] == ["number", "null"]
    assert listing["company"]["type"] == ["string", "null"]
    assert metadata["output_schema"]["properties"]["error"]["type"] == ["string", "null"]

    calls = []
    response = {"success": True, "error": None, "results": [{"id": 1, "results": [
        {"title": "Engineer", "remote": None, "salary_min": None, "company": None},
    ]}]}

    def runner(app_id, skill_id, input_data, **options):
        calls.append((app_id, skill_id, input_data, options))
        return response

    input_data = {"requests": [{"query": "engineer", "country": "SE", "provider": "JobTech"}]}
    assert GeneratedAppSkills(runner).jobs.search(input_data) == response
    assert calls == [("jobs", "search", input_data, {"prompt_injection_protection": None})]
