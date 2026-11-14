# backend/tests/test_figma_get_design_skill.py
#
# design.get_design against a stateful fake Figma REST API (httpx transport):
# URL parsing, shallow file and node reads, vector geometry dropping, node cap,
# variables/images call budget, rate-limit and error classification, token
# context checks and the code handoff tokens.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import pytest

from backend.shared.providers.figma.client import FigmaInputError, parse_figma_reference
from backend.shared.python_utils.figma_design_handoff import simplify_nodes
from backend.tests.fake_figma_api import FILE_KEY, FakeFigmaApi

TOKENS = {"ath_1": "synthetic-figma-token"}
URL = f"https://www.figma.com/design/{FILE_KEY}/Synthetic-Landing"


async def _run(fake: FakeFigmaApi, tokens=TOKENS, **request):
    from backend.apps.design.skills.get_design_skill import GetDesignSkill

    skill = object.__new__(GetDesignSkill)
    return await skill.execute(
        requests=[{"access_token_handle": "ath_1", **request}],
        connected_account_access_tokens=tokens, figma_client_factory=fake.client_factory(),
    )


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
@pytest.mark.parametrize("kind", ["design", "file", "proto", "board"])
def test_url_kinds_parse_to_file_key(kind) -> None:
    assert parse_figma_reference(f"https://www.figma.com/{kind}/{FILE_KEY}/Name") == (FILE_KEY, [])


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
def test_branch_url_uses_branch_key_and_node_id_dash_becomes_colon() -> None:
    url = f"https://www.figma.com/design/{FILE_KEY}/branch/BranchKey12345/Name?node-id=12-34"
    assert parse_figma_reference(url) == ("BranchKey12345", ["12:34"])


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
@pytest.mark.parametrize("url", ["https://evil.example.org/design/AbCdEf1234567890/x", "not a url", "ftp://figma.com/design/AbCdEf1234567890"])
def test_invalid_host_or_garbage_rejected(url) -> None:
    with pytest.raises(FigmaInputError):
        parse_figma_reference(url)


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
def test_more_than_ten_node_ids_rejected() -> None:
    with pytest.raises(FigmaInputError):
        parse_figma_reference(None, FILE_KEY, [f"1:{i}" for i in range(11)])


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content,design-figma.limits.rate-aware
@pytest.mark.anyio
async def test_whole_file_read_is_shallow_and_returns_components_and_styles() -> None:
    fake = FakeFigmaApi()
    result = (await _run(fake, figma_url=URL)).results[0]
    assert result["file"]["name"] == "Synthetic Landing"
    assert [f["name"] for f in result["frames"]] == ["Desktop", "Mobile"]
    assert (result["frames"][0]["width"], result["frames"][0]["height"]) == (1440, 1024)
    assert result["components"][0]["name"] == "Card"
    assert {s["name"] for s in result["styles"]} >= {"Brand/Primary"}
    assert fake.calls("file")[0].url.params["depth"] == "2"


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
@pytest.mark.anyio
async def test_node_read_with_ids_uses_nodes_endpoint() -> None:
    fake = FakeFigmaApi()
    result = (await _run(fake, file_key=FILE_KEY, node_ids=["1-8"])).results[0]
    assert [n["name"] for n in result["nodes"]] == ["Mobile", "Mobile body"]
    assert len(fake.calls("nodes")) == 1 and not fake.calls("file")


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
@pytest.mark.anyio
async def test_vector_geometry_is_dropped() -> None:
    result = (await _run(FakeFigmaApi(), file_key=FILE_KEY)).results[0]
    blob = str(result["nodes"])
    assert "fillGeometry" not in blob and "vectorPaths" not in blob and "M0 0" not in blob
    assert any(n["type"] == "VECTOR" for n in result["nodes"])


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
def test_node_cap_sets_truncated_flag() -> None:
    document = {"id": "0:0", "type": "DOCUMENT", "children": [{"id": f"1:{i}", "type": "FRAME"} for i in range(20)]}
    nodes, truncated = simplify_nodes(document, max_nodes=5)
    assert len(nodes) == 5 and truncated is True
    assert simplify_nodes(document, max_nodes=50)[1] is False


# contract-test: supporting surface=rest_api assertions=design-figma.read.variables-images
@pytest.mark.anyio
async def test_variables_ok_and_values_in_tokens() -> None:
    fake = FakeFigmaApi()
    result = (await _run(fake, file_key=FILE_KEY, include=["variables"])).results[0]
    assert result["variables"]["status"] == "ok" and len(fake.calls("variables")) == 1
    css = result["code_handoff"]["tokens_css"]
    assert "--color-accent: #ff6600;" in css and "--radius-medium: 12px;" in css


# contract-test: supporting surface=rest_api assertions=design-figma.read.variables-images
@pytest.mark.anyio
async def test_variables_not_requested_makes_no_call() -> None:
    fake = FakeFigmaApi()
    result = (await _run(fake, file_key=FILE_KEY)).results[0]
    assert result["variables"]["status"] == "not_requested" and not fake.calls("variables")


# contract-test: supporting surface=rest_api assertions=design-figma.read.variables-images,design-figma.connection.minimal-scopes
@pytest.mark.anyio
async def test_variables_plan_limited_still_returns_rest() -> None:
    fake = FakeFigmaApi(variables_plan_limited=True)
    response = await _run(fake, file_key=FILE_KEY, include=["frames", "variables"])
    result = response.results[0]
    assert result["variables"]["status"] == "plan_limited"
    assert result["frames"] and response.error is None


# contract-test: supporting surface=rest_api assertions=design-figma.read.variables-images
@pytest.mark.anyio
async def test_images_one_call_with_expiry_note() -> None:
    fake = FakeFigmaApi()
    result = (await _run(fake, file_key=FILE_KEY, include=["frames", "images"], image_format="svg")).results[0]
    assert len(fake.calls("images")) == 1
    assert fake.calls("images")[0].url.params["ids"] == "1:2,1:8"
    assert result["images"]["expires_in_days"] == 30
    handoff = result["code_handoff"]
    assert handoff["assets"][0]["expires_in_days"] == 30 and handoff["assets"][0]["format"] == "svg"
    assert any("expire" in note for note in handoff["notes"])
    assert handoff["screens"][0]["image_url"].endswith(".svg")


# contract-test: supporting surface=rest_api assertions=design-figma.limits.rate-aware
@pytest.mark.anyio
async def test_rate_limit_is_classified_and_never_retried() -> None:
    fake = FakeFigmaApi(rate_limit={
        "Retry-After": "42", "X-Figma-Plan-Tier": "starter", "X-Figma-Rate-Limit-Type": "low",
        "X-Figma-Upgrade-Link": "https://www.figma.com/upgrade",
    })
    response = await _run(fake, file_key=FILE_KEY)
    result = response.results[0]
    assert result["error"] == "figma_rate_limited" and result["retryable"] is True
    assert (result["retry_after_seconds"], result["plan_tier"], result["rate_limit_type"]) == (42, "starter", "low")
    assert response.error == "figma_rate_limited" and len(fake.requests) == 1


# contract-test: supporting surface=rest_api assertions=design-figma.read.file-content
@pytest.mark.anyio
async def test_missing_file_is_not_found_not_empty() -> None:
    result = (await _run(FakeFigmaApi(), file_key="ZzZzZzZz12345678")).results[0]
    assert result["error"] == "figma_not_found" and "nodes" not in result


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
@pytest.mark.anyio
async def test_superseded_token_is_retryable_not_reconnect() -> None:
    import httpx

    fake = FakeFigmaApi(fail_next=[httpx.Response(403, json={"status": 403, "err": "Invalid token"})])
    result = (await _run(fake, file_key=FILE_KEY)).results[0]
    assert result["error"] == "figma_token_superseded"
    assert result["retryable"] is True and result["reconnect_required"] is False


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
@pytest.mark.anyio
async def test_unauthorized_requires_reconnect() -> None:
    fake = FakeFigmaApi(access_token="other")
    result = (await _run(fake, file_key=FILE_KEY)).results[0]
    assert result["error"] == "figma_reconnect_required" and result["reconnect_required"] is True


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
@pytest.mark.anyio
@pytest.mark.parametrize("tokens", [None, {}, {"other": "x"}])
async def test_missing_handle_raises_permission_error(tokens) -> None:
    with pytest.raises(PermissionError):
        await _run(FakeFigmaApi(), tokens=tokens, file_key=FILE_KEY)


# contract-test: supporting surface=rest_api assertions=design-figma.handoff.design-to-code
@pytest.mark.anyio
async def test_code_handoff_tokens_from_styles() -> None:
    result = (await _run(FakeFigmaApi(), file_key=FILE_KEY)).results[0]
    handoff = result["code_handoff"]
    assert "--brand-primary: #3355ff;" in handoff["tokens_css"]
    assert "--heading-h1-font-size: 48px;" in handoff["tokens_css"]
    assert handoff["components"][0]["key"] == "abc123"
    assert [s["name"] for s in handoff["screens"]] == ["Desktop", "Mobile"]


# contract-test: supporting surface=rest_api assertions=design-figma.limits.rate-aware
@pytest.mark.anyio
async def test_call_budget_per_request() -> None:
    fake = FakeFigmaApi()
    await _run(fake, file_key=FILE_KEY, include=["frames", "components", "styles", "variables", "images"])
    assert len(fake.calls("file")) == 1 and len(fake.calls("images")) == 1 and len(fake.calls("variables")) == 1
    assert len(fake.requests) == 3
