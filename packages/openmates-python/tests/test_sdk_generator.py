"""OpenMates Python SDK generator contract tests.

Purpose: verify native app-skill SDK methods are generated from app metadata.
Architecture: docs/specs/sdk-cli-parity-v1/spec.yml.
Security: generated wrappers delegate to API-key SDK request helpers only.
Run: python3 -m pytest packages/openmates-python/tests/test_sdk_generator.py
"""

from openmates.generated.app_skills import APP_SKILL_METADATA, GeneratedAppSkills


# contract-test: supporting surface=sdks.pip assertions=audio-generate.surface-parity,audio-speak.surface-parity
def test_generated_metadata_includes_audio_web_search_images_generate_business_and_fitness():
    audio_generate = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "audio" and skill["skill_id"] == "generate"
    )
    audio_speak = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "audio" and skill["skill_id"] == "speak"
    )
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
    code_run = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "code" and skill["skill_id"] == "run"
    )
    models3d_search = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "models3d" and skill["skill_id"] == "search"
    )
    business_financials = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "business" and skill["skill_id"] == "company_financials"
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
    travel_connections = next(
        skill
        for skill in APP_SKILL_METADATA
        if skill["app_id"] == "travel" and skill["skill_id"] == "search_connections"
    )

    assert audio_generate["app_namespace_py"] == "audio"
    assert audio_generate["skill_method_py"] == "generate"
    assert audio_generate["schema"]["properties"]["requests"]["items"]["properties"]["provider"]["enum"] == [
        "elevenlabs"
    ]

    assert audio_speak["app_namespace_py"] == "audio"
    assert audio_speak["skill_method_py"] == "speak"
    assert audio_speak["schema"]["properties"]["requests"]["items"]["properties"]["voice"]["enum"] == [
        "warm_neutral",
        "bright_neutral",
        "calm_narrator",
    ]
    assert audio_speak["schema"]["properties"]["requests"]["items"]["properties"]["model"]["enum"] == [
        "eleven_v3",
        "eleven_multilingual_v2",
        "eleven_flash_v2_5",
    ]
    assert (
        audio_speak["schema"]["properties"]["requests"]["items"]["properties"]["model"]["default"]
        == "eleven_v3"
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

    assert code_run["app_namespace_py"] == "code"
    assert code_run["skill_method_py"] == "run"
    code_run_request = code_run["schema"]["properties"]["requests"]["items"]["properties"]
    assert code_run_request["mode"]["default"] == "direct"
    assert "content_base64" in code_run_request["files"]["items"]["properties"]
    assert (
        code_run["output_schema"]["properties"]["results"]["items"]["properties"]["final"]["properties"]["artifacts"]["items"]["properties"]["download_url"]["type"]
        == "string"
    )

    assert models3d_search["app_namespace_py"] == "models3d"
    assert models3d_search["skill_method_py"] == "search"
    assert "requests" in models3d_search["schema"]["properties"]

    assert business_financials["app_namespace_py"] == "business"
    assert business_financials["skill_method_py"] == "company_financials"
    assert "companies" in business_financials["schema"]["properties"]

    assert fitness_locations["app_namespace_py"] == "fitness"
    assert fitness_locations["skill_method_py"] == "search_locations"
    assert "requests" in fitness_locations["schema"]["properties"]

    assert fitness_classes["app_namespace_py"] == "fitness"
    assert fitness_classes["skill_method_py"] == "search_classes"
    assert "requests" in fitness_classes["schema"]["properties"]

    travel_request = travel_connections["schema"]["properties"]["requests"]["items"]["properties"]
    assert "transitous" in travel_request["providers"]["items"]["enum"]
    assert "owned_passes" in travel_request
    assert "pass_only" in travel_request
    assert travel_request["rail_products"]["items"]["enum"] == [
        "high_speed",
        "intercity",
        "regional_express",
        "regional",
        "s_bahn",
        "subway",
        "tram",
        "bus",
        "ferry",
    ]


# contract-test: supporting surface=sdks.pip assertions=audio-generate.surface-parity,audio-speak.surface-parity
def test_generated_native_methods_delegate_to_runner():
    calls = []

    def run_skill(app_id, skill_id, input_data, **options):
        calls.append({"app_id": app_id, "skill_id": skill_id, "input_data": input_data, "options": options})
        return {"ok": True}

    apps = GeneratedAppSkills(run_skill)
    result = apps.web.search({"requests": [{"query": "hello"}]})
    audio_result = apps.audio.generate({"requests": [{"prompt": "soft tick", "provider": "elevenlabs"}]})
    speech_result = apps.audio.speak({"requests": [{"text": "Welcome back.", "provider": "elevenlabs"}]})
    icon_result = apps.design.search_icons({"requests": [{"query": "home"}]})
    code_run_result = apps.code.run({"requests": [{"mode": "direct", "entry_path": "main.py", "files": []}]})
    fitness_result = apps.fitness.search_classes({"requests": [{"address": "Sorauer Str. 12"}]})
    models3d_result = apps.models3d.search({"requests": [{"query": "benchy"}]})
    business_result = apps.business.company_financials(
        {"companies": [{"query": "CALM"}]},
        prompt_injection_protection=False,
    )

    assert result == {"ok": True}
    assert audio_result == {"ok": True}
    assert speech_result == {"ok": True}
    assert icon_result == {"ok": True}
    assert code_run_result == {"ok": True}
    assert fitness_result == {"ok": True}
    assert models3d_result == {"ok": True}
    assert business_result == {"ok": True}
    assert calls == [
        {"app_id": "web", "skill_id": "search", "input_data": {"requests": [{"query": "hello"}]}, "options": {"prompt_injection_protection": None}},
        {
            "app_id": "audio",
            "skill_id": "generate",
            "input_data": {"requests": [{"prompt": "soft tick", "provider": "elevenlabs"}]},
            "options": {"prompt_injection_protection": None},
        },
        {
            "app_id": "audio",
            "skill_id": "speak",
            "input_data": {"requests": [{"text": "Welcome back.", "provider": "elevenlabs"}]},
            "options": {"prompt_injection_protection": None},
        },
        {"app_id": "design", "skill_id": "search_icons", "input_data": {"requests": [{"query": "home"}]}, "options": {"prompt_injection_protection": None}},
        {
            "app_id": "code",
            "skill_id": "run",
            "input_data": {"requests": [{"mode": "direct", "entry_path": "main.py", "files": []}]},
            "options": {"prompt_injection_protection": None},
        },
        {
            "app_id": "fitness",
            "skill_id": "search_classes",
            "input_data": {"requests": [{"address": "Sorauer Str. 12"}]},
            "options": {"prompt_injection_protection": None},
        },
        {"app_id": "models3d", "skill_id": "search", "input_data": {"requests": [{"query": "benchy"}]}, "options": {"prompt_injection_protection": None}},
        {"app_id": "business", "skill_id": "company_financials", "input_data": {"companies": [{"query": "CALM"}]}, "options": {"prompt_injection_protection": False}},
    ]
