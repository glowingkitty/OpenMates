"""OpenMates Python SDK generator contract tests.

Purpose: verify native app-skill SDK methods are generated from app metadata.
Architecture: docs/specs/sdk-cli-parity-v1/spec.yml.
Security: generated wrappers delegate to API-key SDK request helpers only.
Run: python3 -m pytest packages/openmates-python/tests/test_sdk_generator.py
"""

from openmates.generated.app_skills import APP_SKILL_METADATA, GeneratedAppSkills


def test_generated_metadata_includes_web_search_images_generate_and_fitness():
    web_search = next(
        skill for skill in APP_SKILL_METADATA if skill["app_id"] == "web" and skill["skill_id"] == "search"
    )
    image_generate = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "images" and skill["skill_id"] == "generate"
    )
    design_search_icons = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "design" and skill["skill_id"] == "search_icons"
    )
    models3d_search = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "models3d" and skill["skill_id"] == "search"
    )
    fitness_locations = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "fitness" and skill["skill_id"] == "search_locations"
    )
    fitness_classes = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "fitness" and skill["skill_id"] == "search_classes"
    )

    assert web_search["app_namespace_py"] == "web"
    assert web_search["skill_method_py"] == "search"
    assert web_search["description_key"] == "app_skills.web.search.description"
    assert "requests" in web_search["schema"]["properties"]

    assert image_generate["app_namespace_py"] == "images"
    assert image_generate["skill_method_py"] == "generate"

    assert design_search_icons["app_namespace_py"] == "design"
    assert design_search_icons["skill_method_py"] == "search_icons"
    assert "requests" in design_search_icons["schema"]["properties"]

    assert models3d_search["app_namespace_py"] == "models3d"
    assert models3d_search["skill_method_py"] == "search"
    assert "requests" in models3d_search["schema"]["properties"]

    assert fitness_locations["app_namespace_py"] == "fitness"
    assert fitness_locations["skill_method_py"] == "search_locations"
    assert "requests" in fitness_locations["schema"]["properties"]

    assert fitness_classes["app_namespace_py"] == "fitness"
    assert fitness_classes["skill_method_py"] == "search_classes"
    assert "requests" in fitness_classes["schema"]["properties"]


def test_generated_native_methods_delegate_to_runner():
    calls = []

    def run_skill(app_id, skill_id, input_data, **options):
        calls.append({"app_id": app_id, "skill_id": skill_id, "input_data": input_data, "options": options})
        return {"ok": True}

    apps = GeneratedAppSkills(run_skill)
    result = apps.web.search({"requests": [{"query": "hello"}]}, prompt_injection_protection=False)
    icon_result = apps.design.search_icons({"requests": [{"query": "home"}]})
    fitness_result = apps.fitness.search_classes({"requests": [{"address": "Sorauer Str. 12"}]})
    models3d_result = apps.models3d.search({"requests": [{"query": "benchy"}]})

    assert result == {"ok": True}
    assert icon_result == {"ok": True}
    assert fitness_result == {"ok": True}
    assert models3d_result == {"ok": True}
    assert calls == [
        {"app_id": "web", "skill_id": "search", "input_data": {"requests": [{"query": "hello"}]}, "options": {"prompt_injection_protection": False}},
        {"app_id": "design", "skill_id": "search_icons", "input_data": {"requests": [{"query": "home"}]}, "options": {"prompt_injection_protection": None}},
        {
            "app_id": "fitness",
            "skill_id": "search_classes",
            "input_data": {"requests": [{"address": "Sorauer Str. 12"}]},
            "options": {"prompt_injection_protection": None},
        },
        {"app_id": "models3d", "skill_id": "search", "input_data": {"requests": [{"query": "benchy"}]}, "options": {"prompt_injection_protection": None}},
    ]
