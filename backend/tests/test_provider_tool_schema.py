# contract-test-file: infrastructure
"""Real skill schemas must cross provider boundaries without UI annotations."""

import copy
from pathlib import Path

import yaml

from backend.apps.ai.llm_providers.google_client import _map_tools_to_google_format
from backend.apps.ai.llm_providers.openai_shared import _sanitize_schema_for_llm_providers


def test_weather_tool_schema_is_accepted_by_google_without_mutating_app_schema():
    app_path = Path(__file__).resolve().parents[1] / "apps/weather/app.yml"
    app = yaml.safe_load(app_path.read_text())
    skill = next(skill for skill in app["skills"] if skill["id"] == "forecast")
    original = copy.deepcopy(skill["tool_schema"])
    schema = _sanitize_schema_for_llm_providers(skill["tool_schema"])

    google_tools = _map_tools_to_google_format([{
        "type": "function",
        "function": {"name": "weather-forecast", "description": "Weather forecast", "parameters": schema},
    }])

    assert google_tools[0].function_declarations[0].name == "weather-forecast"
    assert "x-ui" not in schema
    assert "x-ui" not in schema["properties"]["days"]
    assert schema["properties"]["location"]["type"] == "string"
    assert skill["tool_schema"] == original
    assert original["x-ui"]["control"] == "date-range"


def test_extensions_are_removed_at_schema_nodes_not_from_argument_names():
    schema = {
        "type": "object", "x-ui": {"control": "form"},
        "properties": {
            "x-user-field": {"type": "string", "x-ui": {"hidden": True}},
            "rows": {"type": "array", "items": {
                "type": "object", "x-renderer": "card",
                "properties": {"name": {"anyOf": [{"type": "string", "x-ui": {}}]}},
            }},
        },
    }
    clean = _sanitize_schema_for_llm_providers(schema)
    assert clean["properties"]["x-user-field"] == {"type": "string"}
    items = clean["properties"]["rows"]["items"]
    assert "x-renderer" not in items
    assert items["properties"]["name"]["anyOf"] == [{"type": "string"}]
    assert schema["x-ui"] == {"control": "form"}


def test_maps_and_fitness_tools_prepare_together_for_google():
    tools = []
    originals = []
    for app_id, skill_id in [("maps", "search"), ("fitness", "search_classes")]:
        path = Path(__file__).resolve().parents[1] / f"apps/{app_id}/app.yml"
        app = yaml.safe_load(path.read_text())
        skill = next(skill for skill in app["skills"] if skill["id"] == skill_id)
        original = copy.deepcopy(skill["tool_schema"])
        originals.append((skill, original))
        tools.append({"type": "function", "function": {
            "name": f"{app_id}-{skill_id}",
            "parameters": _sanitize_schema_for_llm_providers(skill["tool_schema"]),
        }})

    declarations = _map_tools_to_google_format(tools)[0].function_declarations
    assert [item.name for item in declarations] == ["maps-search", "fitness-search_classes"]
    assert declarations[1].parameters.required == ["requests"]
    for skill, original in originals:
        assert skill["tool_schema"] == original
    assert originals[0][1]["properties"]["requests"]["items"]["properties"]["categories"]["uniqueItems"] is True


# contract-test: supporting surface=cli assertions=hosting-domains.request.validated,hosting-domains.surface-parity
def test_hosting_grouped_tool_schema_accepts_string_and_integer_ids_in_google():
    app_path = Path(__file__).resolve().parents[1] / "apps/hosting/app.yml"
    app = yaml.safe_load(app_path.read_text())
    skill = next(skill for skill in app["skills"] if skill["id"] == "search_domains")
    original = copy.deepcopy(skill["tool_schema"])
    schema = _sanitize_schema_for_llm_providers(skill["tool_schema"])
    google_tools = _map_tools_to_google_format([{
        "type": "function",
        "function": {"name": "hosting-search_domains", "parameters": schema},
    }])
    declaration = google_tools[0].function_declarations[0]
    assert declaration.name == "hosting-search_domains"
    requests = declaration.parameters.properties["requests"]
    assert requests.type.value == "ARRAY"
    assert requests.items.required == ["query"]
    assert {item.type.value for item in requests.items.properties["id"].any_of} == {"STRING", "INTEGER"}
    assert skill["tool_schema"] == original
