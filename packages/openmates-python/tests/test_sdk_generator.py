"""OpenMates Python SDK generator contract tests.

Purpose: verify native app-skill SDK methods are generated from app metadata.
Architecture: docs/specs/sdk-cli-parity-v1/spec.yml.
Security: generated wrappers delegate to API-key SDK request helpers only.
Run: python3 -m pytest packages/openmates-python/tests/test_sdk_generator.py
"""

from openmates.generated.app_skills import APP_SKILL_METADATA, GeneratedAppSkills


def test_generated_metadata_includes_web_search_and_images_generate():
    web_search = next(
        skill for skill in APP_SKILL_METADATA if skill["app_id"] == "web" and skill["skill_id"] == "search"
    )
    image_generate = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "images" and skill["skill_id"] == "generate"
    )

    assert web_search["app_namespace_py"] == "web"
    assert web_search["skill_method_py"] == "search"
    assert web_search["description_key"] == "app_skills.web.search.description"
    assert "requests" in web_search["schema"]["properties"]

    assert image_generate["app_namespace_py"] == "images"
    assert image_generate["skill_method_py"] == "generate"


def test_generated_native_methods_delegate_to_runner():
    calls = []

    def run_skill(app_id, skill_id, input_data):
        calls.append({"app_id": app_id, "skill_id": skill_id, "input_data": input_data})
        return {"ok": True}

    apps = GeneratedAppSkills(run_skill)
    result = apps.web.search({"requests": [{"query": "hello"}]})

    assert result == {"ok": True}
    assert calls == [
        {"app_id": "web", "skill_id": "search", "input_data": {"requests": [{"query": "hello"}]}},
    ]
