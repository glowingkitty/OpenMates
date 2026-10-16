"""Bounded first-turn setup overlap and optional debug lifecycle coverage."""

# contract-test-file: infrastructure

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace


TASK_SOURCE = Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py"


def _isolated_function(name, namespace):
    tree = ast.parse(TASK_SOURCE.read_text())
    function = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name)
    function.body = [node for node in function.body if not isinstance(node, ast.ImportFrom)]
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, f"<{name}>", "exec"), namespace)
    return namespace[name]


def test_pending_empty_details_becomes_eligible_only_after_complete_proof():
    admission = {
        "scope_complete": False, "context_revision": "server-admission-v1",
        "active_project_id": None, "active_project_activation_id": None,
        "active_focus_id": None, "accepted_plan_ref": None,
        "explicit_related_task_ids": [],
    }
    request = SimpleNamespace(
        chat_has_title=False, message_id="m1", current_user_content="Hello",
        message_history=[SimpleNamespace(role="user", message_id="m1", content="Hello")],
        admission_context=admission,
    )
    routing = {"project_target_outcome": "none", "selected_app_ids": []}
    calls = []

    def complete_proof(req, *_args):
        calls.append("complete")
        return req.admission_context["scope_complete"] is True and not req.admission_context["active_project_id"]

    def candidate(req, *_args):
        calls.append("candidate")
        return req.admission_context["context_revision"] == "server-admission-v1"

    eligible = _isolated_function("_can_overlap_first_turn_reads", {
        "_simple_context_fast_path": complete_proof,
        "_stage_one_project_none_candidate": candidate,
    })
    assert not eligible(request, {"routing": routing})
    assert eligible(request, {"routing": routing}, allow_pending_details=True)
    assert calls == ["complete", "complete", "candidate"]

    # The details phase completed an empty server admission.
    admission["scope_complete"] = True
    assert eligible(request, {"routing": routing})
    # A private scope can never pass the complete proof or pending candidate.
    admission["active_project_id"] = "private-project"
    assert not eligible(request, {"routing": routing}, allow_pending_details=True)

    body = TASK_SOURCE.read_text().split("async def _async_process_ai_skill_ask_task(", 1)[1]
    assert body.index('phase="details", encryption_service=encryption_service_instance') < body.index(
        "first_turn_overlap = (")
    assert body.index("first_turn_overlap = (") < body.index("summary_task = asyncio.create_task")
    assert body.index("first_turn_overlap = (") < body.index("embed_task = asyncio.create_task")
    assert body.index("if delayed_first_turn_summary and not first_turn_overlap:") < body.index(
        "summary_task = asyncio.create_task")


def test_optional_debug_cache_runs_past_first_chunk_and_cannot_hold_completion():
    from unittest.mock import Mock

    body = TASK_SOURCE.read_text().split("async def _async_process_ai_skill_ask_task(", 1)[1]
    assert body.index("# --- Step 2: Main Processing") < body.index(
        "_consume_main_processing_stream(") < body.index("wait_for_budget=True")
    assert body.index("before_first_chunk_publish=publish_initial_metadata_after_seal") < body.index(
        "wait_for_budget=True")
    assert "accept_write=lambda:" in body
    assert "write_cancelled=debug_cache_write_cancelled" in body

    clock = Mock(side_effect=lambda: asyncio.get_running_loop().time())
    log = Mock()
    settle = _isolated_function("_settle_optional_debug_cache", {
        "asyncio": asyncio, "time": SimpleNamespace(monotonic=clock),
        "_OPTIONAL_DEBUG_CACHE_BUDGET_S": 0.03,
        "_OPTIONAL_DEBUG_CANCEL_GRACE_S": 0.01,
        "_consume_optional_debug_result": _isolated_function("_consume_optional_debug_result", {}),
        "logger": SimpleNamespace(info=log),
    })

    async def check():
        events = []
        stopped = asyncio.Event()

        async def delayed_debug():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def stream_consumer(before_first_chunk_publish):
            await before_first_chunk_publish()
            events.append("first_chunk")
            return "response"

        async def metadata_barrier():
            events.append("metadata")

        started_at = asyncio.get_running_loop().time()
        debug_task = asyncio.create_task(delayed_debug())
        # The actual consumer callback remains the visible-chunk barrier.
        response = await stream_consumer(metadata_barrier)
        assert response == "response"
        assert events == ["metadata", "first_chunk"]
        assert not debug_task.done()
        write_cancelled = asyncio.Event()
        await asyncio.wait_for(settle(
            debug_task, started_at, wait_for_budget=True,
            write_cancelled=write_cancelled,
        ), 0.15)
        assert write_cancelled.is_set()
        assert stopped.is_set() and debug_task.cancelled()
        assert log.call_args.args[1] == "deadline_cancelled"

        # If streaming itself fails, exit cleanup cancels without waiting for
        # the rest of the creation-time budget or blocking queued handoff.
        stopped.clear()
        started_at = asyncio.get_running_loop().time()
        debug_task = asyncio.create_task(delayed_debug())
        await asyncio.sleep(0)
        try:
            raise RuntimeError("provider failed")
        except RuntimeError:
            write_cancelled = asyncio.Event()
            await asyncio.wait_for(settle(
                debug_task, started_at, wait_for_budget=False,
                write_cancelled=write_cancelled,
            ), 0.1)
        assert write_cancelled.is_set()
        assert stopped.is_set() and debug_task.cancelled()
        assert log.call_args.args[1] == "exit_cancelled"

        # Cancellation while joining drains the writer and reaches the caller.
        stopped.clear()
        started_at = asyncio.get_running_loop().time()
        debug_task = asyncio.create_task(delayed_debug())
        write_cancelled = asyncio.Event()
        joiner = asyncio.create_task(settle(
            debug_task, started_at, wait_for_budget=True,
            write_cancelled=write_cancelled,
        ))
        await asyncio.sleep(0)
        joiner.cancel()
        try:
            await joiner
        except asyncio.CancelledError:
            pass
        else:
            assert False, "caller cancellation must propagate"
        assert write_cancelled.is_set()
        assert stopped.is_set() and debug_task.cancelled()
        assert log.call_args.args[1] == "caller_cancelled"

        async def failed_debug():
            raise RuntimeError("private payload must stay out of logs")

        started_at = asyncio.get_running_loop().time()
        debug_task = asyncio.create_task(failed_debug())
        await asyncio.sleep(0)
        await settle(debug_task, started_at, wait_for_budget=True)
        assert log.call_args.args[1] == "failed"
        assert "private payload" not in str(log.call_args)

    asyncio.run(check())


# contract-test: direct surface=cli assertions=chat-processing-feedback.turn-lifecycle
def test_actual_stream_consumer_publishes_while_optional_debug_is_delayed(monkeypatch):
    """The real consumer can publish a visible chunk while debug cache is pending."""
    from unittest.mock import AsyncMock, Mock

    from backend.apps.ai.processing.preprocessor import PreprocessingResult
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.tasks import stream_consumer

    published = []
    stopped = asyncio.Event()
    log = Mock()
    settle = _isolated_function("_settle_optional_debug_cache", {
        "asyncio": asyncio, "time": SimpleNamespace(monotonic=lambda: asyncio.get_running_loop().time()),
        "_OPTIONAL_DEBUG_CACHE_BUDGET_S": 0.03,
        "_OPTIONAL_DEBUG_CANCEL_GRACE_S": 0.01,
        "_consume_optional_debug_result": _isolated_function("_consume_optional_debug_result", {}),
        "logger": SimpleNamespace(info=log),
    })

    async def processing_stream(**_kwargs):
        yield "Visible answer."
        yield stream_consumer.MistralUsage(prompt_tokens=20, completion_tokens=2, total_tokens=22)

    async def publish(_cache, _channel, payload, *_args):
        published.append(payload)

    async def delayed_debug():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(stream_consumer, "handle_main_processing", processing_stream)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(stream_consumer, "_handle_normal_billing", AsyncMock(return_value={"total_credits": 22}))
    monkeypatch.setattr(stream_consumer, "log_main_llm_stream_aggregated_output", Mock())
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="hash-1", message_history=[], is_incognito=True,
    )

    async def check():
        started_at = asyncio.get_running_loop().time()
        debug_task = asyncio.create_task(delayed_debug())
        result = await asyncio.wait_for(stream_consumer._consume_main_processing_stream(
            task_id="task-1", request_data=request,
            preprocessing_result=PreprocessingResult(can_proceed=True),
            base_instructions={}, directus_service=None, encryption_service=None,
            user_vault_key_id=None, all_mates_configs=[], discovered_apps_metadata={},
            cache_service=SimpleNamespace(), before_first_chunk_publish=None,
        ), 2)
        assert result[0] == "Visible answer."
        assert published and not debug_task.done()
        await asyncio.wait_for(settle(debug_task, started_at, wait_for_budget=True), 0.15)
        assert stopped.is_set() and debug_task.cancelled()
        assert log.call_args.args[1] == "deadline_cancelled"

    asyncio.run(check())
