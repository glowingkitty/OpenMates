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
