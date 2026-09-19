# contract-test-file: infrastructure
"""Contracts for bounded preprocessing prompt construction."""

import ast
import json

from pathlib import Path

import yaml


BASE_INSTRUCTIONS = (
    Path(__file__).resolve().parents[1] / "apps" / "ai" / "base_instructions.yml"
)
PREPROCESSOR = Path(__file__).resolve().parents[1] / "apps" / "ai" / "processing" / "preprocessor.py"


def _preprocessing_tool() -> dict:
    document = yaml.safe_load(BASE_INSTRUCTIONS.read_text(encoding="utf-8"))
    return document["preprocess_request_tool"]["function"]


def test_dynamic_catalogues_have_one_canonical_expansion_site() -> None:
    """Large catalogues must not be repeated inside one provider request."""
    tool = _preprocessing_tool()
    serialized = yaml.safe_dump(tool, sort_keys=False)

    assert serialized.count("{AVAILABLE_APP_SKILLS}") == 1
    assert serialized.count("{AVAILABLE_FOCUS_MODES}") == 1
    assert serialized.count("{TOPIC_AREAS_LIST}") == 1
    assert serialized.count("{AVAILABLE_APP_SETTINGS_AND_MEMORIES}") == 1
    assert serialized.count("{RECENT_SKILL_ACTIVITY}") == 1


def test_static_routing_contract_stays_compact() -> None:
    """Verbose duplicated policy must not silently regrow the foreground prompt."""
    serialized = json.dumps(_preprocessing_tool(), separators=(",", ":"))

    assert len(serialized) < 7000


def test_catalogue_output_fields_reference_canonical_guidance() -> None:
    tool = _preprocessing_tool()
    properties = tool["parameters"]["properties"]

    assert "catalogue above" in properties["relevant_focus_modes"]["description"]
    assert "topic catalogue above" in properties["topic_area"]["description"]


def test_healthy_preprocessing_path_has_one_provider_call_site() -> None:
    module = ast.parse(PREPROCESSOR.read_text(encoding="utf-8"))
    handle = next(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "handle_preprocessing"
    )
    calls = [
        node
        for node in ast.walk(handle)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "call_preprocessing_llm"
    ]
    assert len(calls) == 1


def test_single_routing_schema_contains_all_response_critical_fields() -> None:
    properties = _preprocessing_tool()["parameters"]["properties"]
    for field in (
        "topic_area",
        "topic_shift",
        "harmful_or_illegal",
        "misuse_risk",
        "output_language",
        "title",
        "icon_names",
    ):
        assert field in properties
