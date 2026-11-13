"""Offline tests for the preboot-v2 start/step protocol of the in-VM browser runtime.

Playwright is replaced by small fakes; the pure decision helpers are tested directly.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.providers import web_browse_runtime as rt


def make_runtime(url="about:blank", allowed=True):
    page = SimpleNamespace(
        url=url,
        main_frame=object(),
        title=AsyncMock(return_value="t"),
        goto=AsyncMock(),
        mouse=SimpleNamespace(click=AsyncMock(), wheel=AsyncMock()),
        keyboard=SimpleNamespace(press=AsyncMock()),
        go_back=AsyncMock(),
    )
    context = SimpleNamespace(
        storage_state=AsyncMock(return_value={"cookies": [], "origins": []})
    )
    runtime = rt.BrowseRuntime(page, context, AsyncMock(return_value=allowed))
    runtime.settle = AsyncMock()
    return runtime


def observation(url, **extra):
    return {
        "url": url,
        "title": "Page",
        "text": "hello",
        "document_text": "hello",
        "controls": [{"id": "0", "kind": "click", "href": url + "?token=x"}],
        "links": [],
        "tables": [],
        "dialogs": [],
        "scroll": {"y": 0, "height": 10, "viewport": 5},
        "has_private_input": False,
        **extra,
    }


def stub_observe(runtime):
    async def observe_page(with_screenshot):
        runtime.snapshot_url = runtime.page.url
        runtime.observation_id = "obs-next"
        return {"observation_id": "obs-next", "shot": with_screenshot}

    runtime.observe_page = observe_page


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.lifecycle
@pytest.mark.asyncio
async def test_start_returns_observation_and_timings_and_enforces_pristine():
    runtime = make_runtime()
    stub_observe(runtime)
    result = await runtime.command(
        {"operation": "start", "url": "https://example.com/", "require_pristine": True}
    )
    assert result["control"] == "ai" and result["runtime_protocol"] == "preboot-v2"
    assert result["pristine"] is True and result["observation"]["shot"] is True
    assert set(result["timings"]) == {
        "ready",
        "pristine",
        "navigate",
        "settle",
        "observe",
    }
    runtime.page.goto.assert_awaited_once()
    runtime.settle.assert_awaited_once()

    dirty = make_runtime(url="https://example.com/")
    stub_observe(dirty)
    with pytest.raises(ValueError, match="pristine"):
        await dirty.command(
            {
                "operation": "start",
                "url": "https://example.com/",
                "require_pristine": True,
            }
        )
    dirty.page.goto.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.asyncio
async def test_start_refuses_a_crawler_excluded_destination():
    runtime = make_runtime(allowed=False)
    stub_observe(runtime)
    with pytest.raises(ValueError, match="Crawler"):
        await runtime.command({"operation": "start", "url": "https://example.com/"})
    runtime.page.goto.assert_not_awaited()


def ready_for_step(runtime, url="https://example.com/"):
    runtime.page.url = url
    runtime.snapshot_url = url
    runtime.observation_id = "obs-1"
    stub_observe(runtime)


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.asyncio
async def test_step_runs_batch_in_order_and_stops_after_a_url_change():
    runtime = make_runtime()
    ready_for_step(runtime)
    runtime.prepare = AsyncMock(return_value={"x": 1, "y": 2, "frame": False})

    async def click(x, y):
        runtime.page.url = "https://example.com/next"

    runtime.page.mouse.click = AsyncMock(side_effect=click)
    result = await runtime.command(
        {
            "operation": "step",
            "observation_id": "obs-1",
            "actions": [
                {"kind": "click", "target": "3"},
                {"kind": "click", "target": "4"},
                {"kind": "scroll", "delta": 100},
            ],
        }
    )
    assert [r["outcome"] for r in result["results"]] == [
        "executed",
        "skipped",
        "skipped",
    ]
    assert runtime.page.mouse.click.await_count == 1
    assert result["observation"]["shot"] is False
    assert set(result["timings"]) == {"act", "settle", "observe"}


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.asyncio
async def test_step_rejects_a_stale_target_without_input_and_skips_the_rest():
    runtime = make_runtime()
    ready_for_step(runtime)
    runtime.prepare = AsyncMock(return_value=None)
    result = await runtime.command(
        {
            "operation": "step",
            "observation_id": "obs-1",
            "screenshot": True,
            "actions": [{"kind": "click", "target": "0"}, {"kind": "wait"}],
        }
    )
    assert [r["outcome"] for r in result["results"]] == ["rejected", "skipped"]
    runtime.page.mouse.click.assert_not_awaited()
    assert result["observation"]["shot"] is True


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_step_reports_uncertain_after_input_failure_and_stops():
    runtime = make_runtime()
    ready_for_step(runtime)
    runtime.prepare = AsyncMock(return_value={"x": 1, "y": 2, "frame": False})
    runtime.page.mouse.click = AsyncMock(side_effect=RuntimeError("lost"))
    result = await runtime.command(
        {
            "operation": "step",
            "observation_id": "obs-1",
            "actions": [{"kind": "click", "target": "0"}, {"kind": "back"}],
        }
    )
    assert [r["outcome"] for r in result["results"]] == ["uncertain", "skipped"]
    assert "lost" not in str(result["results"])
    runtime.page.go_back.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observation_id,control",
    [("old", "ai"), (None, "ai"), ("obs-1", "user")],
)
async def test_step_rejects_stale_observation_or_wrong_control_before_any_input(
    observation_id, control
):
    runtime = make_runtime()
    ready_for_step(runtime)
    runtime.control = control
    runtime.prepare = AsyncMock()
    with pytest.raises(ValueError):
        await runtime.command(
            {
                "operation": "step",
                "observation_id": observation_id,
                "actions": [{"kind": "wait"}],
            }
        )
    runtime.prepare.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.asyncio
async def test_step_consumes_the_observation_so_a_replay_is_rejected():
    runtime = make_runtime()
    ready_for_step(runtime)
    runtime.observation_id = "obs-1"
    runtime.observe_page = AsyncMock(return_value={"observation_id": "x"})
    body = {
        "operation": "step",
        "observation_id": "obs-1",
        "actions": [{"kind": "wait"}],
    }
    await runtime.command(body)
    with pytest.raises(ValueError):
        await runtime.command(body)


@pytest.mark.parametrize(
    "actions",
    [
        [],
        [{"kind": "wait"}] * 7,
        [{"kind": "eval", "code": "1"}],
        [{"kind": "click", "target": "abc"}],
        [{"kind": "click", "selector": "#x"}],
        [{"kind": "type", "target": "1", "text": "x" * 2001}],
        [{"kind": "goto", "url": "https://example.com/"}, {"kind": "wait"}],
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
def test_action_vocabulary_is_fixed_and_goto_is_single(actions):
    with pytest.raises(ValueError):
        rt.validate_actions(actions)


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
def test_valid_batch_is_normalised():
    actions = rt.validate_actions(
        [
            {"kind": "type", "target": 2, "text": "q", "submit": True},
            {"kind": "scroll", "delta": 99999},
        ]
    )
    assert actions[0] == {"kind": "type", "target": "2", "text": "q", "submit": True}
    assert actions[1]["delta"] == 800


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_type,consulted",
    [("document", True), ("image", False), ("script", False), ("xhr", False)],
)
async def test_robots_is_consulted_for_documents_only(resource_type, consulted):
    runtime = make_runtime()
    route = SimpleNamespace(
        request=SimpleNamespace(
            url="https://example.com/x",
            resource_type=resource_type,
            is_navigation_request=lambda: resource_type == "document",
            frame=runtime.page.main_frame,
        ),
        continue_=AsyncMock(),
        abort=AsyncMock(),
    )
    await runtime.guard(route)
    assert runtime.crawler_allowed.await_count == (1 if consulted else 0)
    route.continue_.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
@pytest.mark.asyncio
async def test_excluded_document_is_aborted_and_marks_the_main_frame_blocked():
    runtime = make_runtime(allowed=False)
    route = SimpleNamespace(
        request=SimpleNamespace(
            url="https://example.com/x",
            resource_type="document",
            is_navigation_request=lambda: True,
            frame=runtime.page.main_frame,
        ),
        continue_=AsyncMock(),
        abort=AsyncMock(),
    )
    await runtime.guard(route)
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()
    assert runtime.access_failure


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
def test_block_detection_is_structural():
    article = "A long article about web security. " * 100 + " It mentions captcha once."
    assert rt.block_reason(None, "Article", article, False) is None
    assert rt.block_reason(None, "Check", "Please verify you are human", False)
    assert rt.block_reason(None, "Access denied", "", False)
    assert rt.block_reason(None, "Shop", article, True)
    assert rt.block_reason("denied", "Shop", article, False) == "denied"


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
def test_finalize_observation_blocks_short_gate_only():
    gate = rt.finalize_observation(
        observation("https://example.com/", document_text="verify you are human"),
        None,
    )
    assert gate["blocked_reason"] and gate["controls"] == []
    long_text = "Notes about captcha design. " * 200
    page = rt.finalize_observation(
        observation("https://example.com/", document_text=long_text), None
    )
    assert "blocked_reason" not in page and page["controls"]


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data
def test_document_text_is_truncated_not_rejected():
    assert rt.truncate_document_text("a" * 120000) == ("a" * 120000, False)
    text, truncated = rt.truncate_document_text("a" * 120001)
    assert len(text) == 120000 and truncated
    page = rt.finalize_observation(
        observation("https://example.com/", document_text="b" * 120001), None
    )
    assert (
        page["document_text_truncated"] is True and len(page["document_text"]) == 120000
    )


# contract-test: supporting surface=rest_api assertions=web-browse.sign-in
def test_private_page_is_blanked_and_urls_are_redacted():
    page = rt.finalize_observation(
        observation("https://example.com/?token=abc", has_private_input=True), None
    )
    assert (
        page["controls"] == [] and page["document_text"] == "" and page["dialogs"] == []
    )
    plain = rt.finalize_observation(observation("https://example.com/?token=abc"), None)
    assert "abc" not in plain["url"] and "abc" not in plain["controls"][0]["href"]


# contract-test: supporting surface=rest_api assertions=web-browse.sign-in,web-browse.control-loop
def test_snapshot_excludes_private_fields_and_covers_shadow_and_frames():
    assert "!privateField(e)" in rt.SNAPSHOT
    assert "e.shadowRoot" in rt.SNAPSHOT and "contentDocument" in rt.SNAPSHOT
    assert "in_viewport" in rt.SNAPSHOT and "dialog[open]" in rt.SNAPSHOT
    assert "scrollIntoView" in rt.PREPARE_JS


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.structured-data
def test_snapshot_keeps_controls_nearest_the_viewport_and_links_beyond_the_window():
    # A long product grid: menu links first in page order must not take the
    # control window from the offers the user is looking at.
    assert "__MAX_" not in rt.SNAPSHOT
    assert f"ranked.slice(0,{rt.MAX_CONTROLS})" in rt.SNAPSHOT
    assert "sort((a,b)=>a.d-b.d||a.i-b.i)" in rt.SNAPSHOT
    # The chosen controls keep page order, so ids stay stable and readable.
    assert "sort((a,b)=>a.i-b.i)" in rt.SNAPSHOT
    # Links come from every candidate, nearest first, unique and bounded.
    assert f".slice(0,{rt.MAX_LINKS})" in rt.SNAPSHOT and "seenLinks" in rt.SNAPSHOT
    assert rt.MAX_CONTROLS < rt.MAX_LINKS < rt.MAX_CANDIDATES


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
def test_batch_stop_and_settle_decisions():
    assert rt.batch_stops("a", "b", 0, 0)
    assert rt.batch_stops("a", "a", 0, 1)
    assert not rt.batch_stops("a", "a", 2, 2)
    assert rt.settle_ready(0, 0.3, 0.5)
    assert not rt.settle_ready(1, 5, 5)
    assert not rt.settle_ready(0, 0.1, 5)
    assert not rt.settle_ready(0, 5, 0.1)
