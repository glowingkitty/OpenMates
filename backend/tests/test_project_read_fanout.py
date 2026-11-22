"""Multi-path project_read_text fan-out (hosted sandbox) and tool schema."""

import pytest

from backend.apps.ai.processing import project_read_fanout as fanout
from backend.apps.ai.processing.project_file_tools import build_project_file_tools


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
def test_normalize_read_paths_dedupes_and_orders() -> None:
    assert fanout.normalize_read_paths({"path": "a", "paths": ["b", "a", 3, ""]}) == ["a", "b"]


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
@pytest.mark.asyncio
async def test_fan_out_merges_one_result_per_path(monkeypatch) -> None:
    calls = []

    async def fake(*, operation, operation_arguments, **kwargs):
        calls.append(operation_arguments["path"])
        return {"status": "completed", "operation_id": "op", "content": operation_arguments["path"]}

    monkeypatch.setattr(fanout, "run_project_tool_in_sandbox", fake)
    result = await fanout.run_read_text_in_sandbox(operation="read_text", operation_arguments={"paths": ["a", "b"]})
    assert calls == ["a", "b"]
    assert [row["path"] for row in result["files"]] == ["a", "b"]


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
@pytest.mark.asyncio
async def test_fan_out_rejects_too_many_and_device_source(monkeypatch) -> None:
    async def device(**kwargs):
        return None

    monkeypatch.setattr(fanout, "run_project_tool_in_sandbox", device)
    many = await fanout.run_read_text_in_sandbox(
        operation="read_text", operation_arguments={"paths": [f"f{i}" for i in range(11)]})
    assert many["status"] == "rejected"
    remote = await fanout.run_read_text_in_sandbox(operation="read_text", operation_arguments={"paths": ["a", "b"]})
    assert remote["status"] == "rejected"


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
def test_read_tool_schema_accepts_paths() -> None:
    import inspect
    params = inspect.signature(build_project_file_tools).parameters
    kwargs = {name: None for name, p in params.items() if p.default is inspect._empty}
    tools = build_project_file_tools(**kwargs)
    read = next(t for t in tools if t["function"]["name"] == "project_read_text")
    assert read["function"]["parameters"]["properties"]["paths"]["maxItems"] == 10


def _schema_nodes(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _schema_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _schema_nodes(value)


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
def test_project_tool_schemas_are_accepted_by_gemini() -> None:
    # Gemini rejects the whole request (400 "required: only allowed for OBJECT type") when a
    # schema branch lists `required` without being an object, e.g. anyOf: [{"required": ["path"]}].
    import inspect
    params = inspect.signature(build_project_file_tools).parameters
    kwargs = {name: None for name, p in params.items() if p.default is inspect._empty}
    for tool in build_project_file_tools(**kwargs):
        for node in _schema_nodes(tool["function"]["parameters"]):
            if "required" in node:
                assert node.get("type") == "object", (tool["function"]["name"], node)
                assert set(node["required"]) <= set(node.get("properties", {})), (tool["function"]["name"], node)
