"""
Regression tests for AI ask task chat-history boundaries.

Compression summaries are server-readable context for model processing. They
must stay out of Directus chat history unless a client supplies client-encrypted
ciphertext for that history entry.
"""

# contract-test-file: infrastructure

import ast
from pathlib import Path


def test_early_typing_skips_duplicate_late_key_read_and_payload():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    late_region = source.split("# Persist server provider/region on preprocessing_result", maxsplit=1)[1]
    late_region = late_region.split("# CRITICAL: Skip WebSocket events for external requests", maxsplit=1)[0]
    assert "preprocessing_result.server_provider_name = provider_name" in late_region
    assert "preprocessing_result.server_region = server_region" in late_region

    guards = [node for node in ast.walk(tree) if isinstance(node, ast.If)
              and ast.unparse(node.test) == "not typing_lifecycle.started"
              and any(isinstance(child, ast.Call)
                      and isinstance(child.func, ast.Attribute)
                      and child.func.attr == "get_chat_list_item_data"
                      for child in ast.walk(node))]
    assert len(guards) == 1
    guarded = ast.get_source_segment(source, guards[0])
    assert "encrypted_chat_key_for_typing" in guarded
    assert '"event_for_client": "ai_typing_started"' in guarded
    assert "typing_payload_data = {}" in late_region.split("if not typing_lifecycle.started:", maxsplit=1)[0]
    assert "late_payload=typing_payload_data" in source


def test_chat_compression_does_not_persist_server_encrypted_summary_to_history():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    compression_block = source.split("async def _compress_for_selected_model(", maxsplit=1)[1]
    compression_block = compression_block.split("async def _async_process_ai_skill_ask_task(", maxsplit=1)[0]

    assert "set_ai_messages_history" in compression_block
    assert "persist_new_chat_message" not in compression_block


def test_explicit_focus_override_preserves_canonical_activation_pipeline():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    main_processor_source = (
        Path(__file__).resolve().parents[1] / "processing" / "main_processor.py"
    ).read_text()
    explicit_activation_block = main_processor_source.split(
        "# --- User-requested focus mode: bypass LLM + countdown ---",
        maxsplit=1,
    )[1].split("# === BUILD MODEL FALLBACK LIST ===", maxsplit=1)[0]

    assert "request_data.active_focus_id = requested_focus_id" not in source
    assert "preprocessing_result.enable_subchats = resolve_subchat_enablement(" not in source
    assert "user_requested_focus_only and relevant_focus_modes and not has_active_focus_mode" in explicit_activation_block
    assert "countdown=0" in explicit_activation_block


def test_focus_mode_continuations_preserve_recovery_identity():
    ai_app_root = Path(__file__).resolve().parents[1]
    backend_root = ai_app_root.parents[1]
    main_processor_source = (ai_app_root / "processing" / "main_processor.py").read_text()
    mock_replay_source = (ai_app_root / "testing" / "mock_replay.py").read_text()
    auto_confirm_source = (ai_app_root / "tasks" / "focus_mode_auto_confirm_task.py").read_text()
    ask_task_source = (ai_app_root / "tasks" / "ask_skill_task.py").read_text()
    ask_skill_source = (ai_app_root / "skills" / "ask_skill.py").read_text()
    stream_consumer_source = (ai_app_root / "tasks" / "stream_consumer.py").read_text()
    rejection_source = (
        backend_root
        / "core/api/app/routes/handlers/websocket_handlers/focus_mode_rejected_handler.py"
    ).read_text()

    recovery_fields = (
        "recovery_inference_task_id",
        "recovery_preflight_id",
        "recovery_turn_id",
        "recovery_public_key",
        "chat_key_version",
    )

    for field in recovery_fields:
        assert main_processor_source.count(f'"{field}"') >= 2
        assert f'"{field}"' in mock_replay_source
        assert f'"{field}"' in auto_confirm_source
        assert f'"{field}"' in rejection_source

    assert "def resolved_recovery_inference_task_id" in ask_skill_source
    assert "request_data.resolved_recovery_inference_task_id()" in ask_task_source
    assert "request_data.resolved_recovery_inference_task_id()" in stream_consumer_source
    assert "request_data.resolved_recovery_inference_task_id()" in mock_replay_source
    assert "if not _contains_focus_mode_activation_embed(full_response):" in mock_replay_source
    assert (
        "original_request.recovery_task_id or original_request.recovery_inference_task_id"
        in stream_consumer_source
    )

# contract: a completed durable claim and validated account precede the active
# summary write; every early preparation exit drains that write before returning.
def test_preparation_overlap_runs_concurrently_and_drains_early_exit():
    import asyncio
    from contextlib import asynccontextmanager

    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    helper = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_overlap_preparation")
    module = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"asyncio": asyncio, "asynccontextmanager": asynccontextmanager}
    exec(compile(module, "<preparation-overlap>", "exec"), namespace)
    overlap = namespace["_overlap_preparation"]

    async def check():
        started = asyncio.Event()
        release = asyncio.Event()
        drained = asyncio.Event()

        async def delayed_write():
            started.set()
            try:
                await release.wait()
            finally:
                drained.set()

        async with overlap(delayed_write()) as task:
            await started.wait()
            assert not task.done()
            release.set()
            await task
        assert drained.is_set()

        started.clear()
        drained.clear()
        release.clear()
        try:
            async with overlap(delayed_write()):
                await started.wait()
                raise ValueError("preparation failed")
        except ValueError:
            pass
        else:
            assert False, "preparation error must propagate"
        assert drained.is_set()

        started.clear()
        drained.clear()
        release.clear()

        async def return_early():
            async with overlap(delayed_write()):
                await started.wait()
                return "duplicate delivery"

        assert await return_early() == "duplicate delivery"
        assert drained.is_set()

    asyncio.run(check())


def test_artifact_preparation_reads_ledger_for_empty_unknown_and_existing_context():
    """Overlap changes scheduling, not historical-reference coverage."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import backend.core.api.app.services.embed_service as embed_module

    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    helper = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_prepare_artifact_context")
    module = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(module)

    class FakeEmbedService:
        def __init__(self, **_kwargs):
            pass

    original_embed_service = embed_module.EmbedService
    embed_module.EmbedService = FakeEmbedService
    try:
        for admission, initial_index, historical in [
            ({"scope_complete": True}, None, {}),
            (None, None, {}),
            ({"scope_complete": False}, {"new.pdf": "embed-new"},
             {"old.pdf": "embed-old", "new.pdf": "embed-new"}),
        ]:
            recover = AsyncMock(return_value={})
            ledger = AsyncMock(return_value=historical)
            historical_context = AsyncMock(return_value="Recovered artifact context")
            namespace = {
                "recover_inline_upload_artifacts": recover,
                "load_and_merge_artifact_ledger": ledger,
                "build_historical_artifact_context": historical_context,
                "logger": SimpleNamespace(warning=lambda *_args: None),
            }
            exec("from __future__ import annotations\n" + ast.unparse(module), namespace)
            request = SimpleNamespace(
                chat_id="chat", user_id_hash="owner", message_history=[],
                current_user_content="Question?", embed_file_path_index=initial_index,
                historical_artifact_context="stale", admission_context=admission,
                is_incognito=False, is_external=False,
            )
            asyncio.run(namespace["_prepare_artifact_context"](
                request, "task", object(), object(), object(), "vault-key",
            ))
            recover.assert_awaited_once()
            ledger.assert_awaited_once()
            assert ledger.await_args.kwargs["current_index"] == (initial_index or {})
            assert request.embed_file_path_index == (historical or None)
            if historical:
                historical_context.assert_awaited_once()
                assert request.historical_artifact_context == "Recovered artifact context"
            else:
                historical_context.assert_not_awaited()
                assert request.historical_artifact_context is None
    finally:
        embed_module.EmbedService = original_embed_service


# contract: summary activation cannot outrun the authority/cache fences, and
# metadata publication consumes the persisted sealed job before visible output.
def test_preparation_and_metadata_join_boundaries():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    body = source.split("async def _async_process_ai_skill_ask_task(", 1)[1]
    assert body.index('"claim_inference"') < body.index("user_vault_key_id = cached_user_data.get")
    assert body.index("user_vault_key_id = cached_user_data.get") < body.index("async with _overlap_preparation(summary_operation)")
    assert body.index("_overlap_preparation(artifact_operation)") < body.index("get_base_instructions()")
    assert body.index("get_discovered_apps_metadata()") < body.index("await artifact_task")
    assert body.index("await artifact_task") < body.index("# --- Step 0: Parse User Overrides")
    assert body.index("await active_summary_task") < body.index("# --- Step 0: Parse User Overrides")
    assert body.index("debug_cache_task = asyncio.create_task(cache_debug_nonfatal())") < body.index(
        'initial_metadata_operation = time_pre_main("metadata_job"')
    assert body.index('initial_metadata_task = asyncio.create_task(initial_metadata_operation)') < body.index(
        "# --- Step 2: Main Processing") < body.index(
            "wait_for_budget=True")
    assert body.index('initial_metadata_job = await time_pre_main("metadata_barrier_wait", initial_metadata_task)') < body.index(
        "metadata_recovery_job=initial_metadata_job", body.index("async def publish_initial_metadata_after_seal"))
    assert body.index("before_first_chunk_publish=publish_initial_metadata_after_seal") < body.index(
        "wait_for_budget=True")
    assert "if not request_data.is_external:" in body
    assert "if not typing_lifecycle.started:" in body

# contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle,chat-queued-followups.admission.synced
# Execute the real failure cleanup functions in isolation because importing the
# full task worker requires its deployed service graph and secrets.
def test_failure_cleanup_preserves_atomic_owner_and_handoff_fences():
    import asyncio
    import builtins
    from enum import Enum
    from types import SimpleNamespace
    from typing import Optional
    from unittest.mock import AsyncMock, Mock, patch

    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    selected = [node for node in tree.body if (
        isinstance(node, ast.ClassDef) and node.name == "_FailureHandoffOutcome"
    ) or (
        isinstance(node, ast.AsyncFunctionDef) and node.name in {
            "_handoff_queued_after_task_failure", "_terminalize_volatile_followers_after_failure",
            "_cleanup_on_task_failure", "_publish_typing_ended",
        }
    )]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Enum": Enum, "Optional": Optional, "AskSkillRequest": object,
        "CacheService": object, "DirectusService": object,
        "EncryptionService": object, "RequiredRecoveryOutputError": RuntimeError,
        "logger": Mock(), "_pause_consumed_steers_after_failure": AsyncMock(return_value=[]),
        "_cleanup_processing_embeds_on_task_failure": AsyncMock(return_value=0),
    }
    exec(compile(module, "<failure-cleanup>", "exec"), namespace)
    dispatch = AsyncMock()
    import_original = builtins.__import__

    def import_stubs(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("queued_steering"):
            return SimpleNamespace(reconcile_queued_revision_quarantine=AsyncMock(return_value=True))
        if name.endswith("async_skill_continuation"):
            return SimpleNamespace(dispatch_deferred_async_skill_continuations=dispatch)
        return import_original(name, globals, locals, fromlist, level)

    async def exercise(queue_state=None, *, handoff=None, cas_result=True):
        dispatch.reset_mock()
        cache = SimpleNamespace(
            get_active_ai_task=AsyncMock(return_value="old-task"),
            lease_queued_message_prefix=AsyncMock(return_value=None),
            complete_active_ai_task_if_queue_empty=AsyncMock(return_value=queue_state),
            clear_active_ai_task_if_matches=AsyncMock(return_value=cas_result),
            publish_event=AsyncMock(),
        )
        request = SimpleNamespace(
            legacy_cutover_task_id="admission", recovery_task_id=None,
            is_incognito=False, is_external=False, chat_id="chat",
        )
        if handoff is not None:
            namespace["_handoff_queued_after_task_failure"] = AsyncMock(return_value=handoff)
        with patch("builtins.__import__", side_effect=import_stubs):
            await namespace["_cleanup_on_task_failure"](
                task_id="old-task", chat_id="chat", message_id="message",
                user_id="user", user_id_hash="hash", user_vault_key_id="vault",
                error_message="private context detail", cache_service=cache,
                directus_service=SimpleNamespace(), request_data=request,
                skill_config_dict={}, terminal_failure_code="client_context_unavailable",
            )
        cache.publish_event.assert_awaited_once()
        event = cache.publish_event.await_args.args[1]
        assert event["task_id"] == "old-task"
        assert "private context detail" not in repr(event)
        return cache, event, dispatch.await_count

    async def exercise_volatile(queue_state, *, queued_follower=False):
        dispatch.reset_mock()
        lease = {"messages": [{"user_id": "user", "user_id_hash": "hash",
                               "message_id": "follower"}], "token": "lease"}
        cache = SimpleNamespace(
            get_active_ai_task=AsyncMock(return_value="old-task"),
            get_consumed_volatile_steers=AsyncMock(return_value=[]),
            lease_queued_message_prefix=AsyncMock(
                side_effect=[lease, None] if queued_follower else [None]),
            acknowledge_queued_message_prefix=AsyncMock(return_value=True),
            complete_active_ai_task_if_queue_empty=AsyncMock(return_value=queue_state),
            clear_active_ai_task_if_matches=AsyncMock(),
            publish_event=AsyncMock(),
        )
        request = SimpleNamespace(
            is_incognito=True, is_external=False, chat_id="chat",
            user_id="user", user_id_hash="hash",
        )
        with patch("builtins.__import__", side_effect=import_stubs):
            await namespace["_cleanup_on_task_failure"](
                task_id="old-task", chat_id="chat", message_id="message",
                user_id="user", user_id_hash="hash", user_vault_key_id="vault",
                error_message="private context detail", cache_service=cache,
                directus_service=SimpleNamespace(), request_data=request,
                terminal_failure_code="client_context_unavailable",
            )
        events = [call.args[1] for call in cache.publish_event.await_args_list]
        typing = [event for event in events if event.get("event_for_client") == "ai_typing_ended"]
        assert len(typing) == 1
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with("chat", "old-task")
        if queued_follower:
            cache.acknowledge_queued_message_prefix.assert_awaited_once_with("chat", lease)
            paused = [event for event in events if event.get("event_for_client") == "queued_handoff_paused"]
            assert len(paused) == 1
            assert paused[0]["payload"]["message_id"] == "follower"
        return typing[0], dispatch.await_count

    async def check():
        # State 1 is the atomic owned clear. No second CAS may race a new task.
        cache, event, dispatched = await exercise(1)
        cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with("chat", "old-task")
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        assert event["terminal_failure_code"] == "client_context_unavailable"
        assert dispatched == 1

        # State 2 and a successful follower handoff retain the newer fence.
        cache, event, dispatched = await exercise(2)
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        assert "terminal_failure_code" not in event
        assert dispatched == 0
        cache, event, dispatched = await exercise(handoff=True)
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
        assert "terminal_failure_code" not in event
        assert dispatched == 0

        # Without handoff, the old matching CAS remains the only release path.
        cache, event, dispatched = await exercise(handoff=False)
        cache.clear_active_ai_task_if_matches.assert_awaited_once_with("chat", "old-task")
        assert event["terminal_failure_code"] == "client_context_unavailable"
        assert dispatched == 1

        # A failed CAS means ownership changed; no terminal code can target it.
        cache, event, dispatched = await exercise(handoff=False, cas_result=False)
        cache.clear_active_ai_task_if_matches.assert_awaited_once_with("chat", "old-task")
        assert "terminal_failure_code" not in event
        assert dispatched == 0

        # Volatile follow-up cleanup uses the same ownership result. A drained
        # follower may publish its pause, but cannot terminalize a newer task.
        event, dispatched = await exercise_volatile(1)
        assert event["terminal_failure_code"] == "client_context_unavailable"
        assert dispatched == 1
        event, dispatched = await exercise_volatile(2, queued_follower=True)
        assert "terminal_failure_code" not in event
        assert dispatched == 0

    asyncio.run(check())


# contract-test: direct surface=cli assertions=chat-processing-feedback.turn-lifecycle
# Complete empty Stage1 may overlap the active-summary mutation and read-only
# artifact lookup with preprocessing, but related reads and provider use must join.
def test_first_turn_overlap_fences_and_drains_delayed_jobs():
    import asyncio

    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_drain_preparation_tasks"]
    assert len(selected) == 1
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"asyncio": asyncio}
    exec(compile(module, "<first-turn-drain>", "exec"), namespace)
    drain = namespace["_drain_preparation_tasks"]

    async def check():
        summary_started = asyncio.Event()
        embed_started = asyncio.Event()
        summary_release = asyncio.Event()
        embed_release = asyncio.Event()
        drained = []

        async def delayed(name, started, release):
            started.set()
            try:
                await release.wait()
                return name
            finally:
                drained.append(name)

        summary = asyncio.create_task(delayed("summary", summary_started, summary_release))
        embed = asyncio.create_task(delayed("embed", embed_started, embed_release))
        await asyncio.wait_for(asyncio.gather(summary_started.wait(), embed_started.wait()), 1)
        assert not summary.done() and not embed.done()
        async def await_related_boundary():
            await summary
            return "related read allowed"
        related_read = asyncio.create_task(await_related_boundary())
        await asyncio.sleep(0)
        assert not related_read.done()
        summary_release.set()
        assert await related_read == "related read allowed"
        assert not embed.done()
        embed_release.set()
        assert await embed == "embed"
        await drain(summary, embed)
        assert sorted(drained) == ["embed", "summary"]

        drained.clear()
        summary_started.clear()
        embed_started.clear()
        summary_release.clear()
        embed_release.clear()
        summary = asyncio.create_task(delayed("summary", summary_started, summary_release))
        embed = asyncio.create_task(delayed("embed", embed_started, embed_release))
        await asyncio.wait_for(asyncio.gather(summary_started.wait(), embed_started.wait()), 1)
        await drain(summary, embed)  # preprocessing rejection / early exit
        assert summary.cancelled() and embed.cancelled()
        assert sorted(drained) == ["embed", "summary"]

    asyncio.run(check())
    body = source.split("async def _async_process_ai_skill_ask_task(", 1)[1]
    assert body.index('stage=durable_claim') < body.index("delayed_first_turn_summary =")
    assert body.index("before_related_summary_read=before_related_summary_read") < body.index(
        "await _drain_preparation_tasks(summary_task, embed_task)")
    assert body.index("prefetched_diffable_embeds = await embed_task") < body.index(
        "# --- Step 2: Main Processing")
    assert body.index('initial_metadata_operation = time_pre_main("metadata_job"') < body.index(
        "_scoped_diffable_embed_prefetch(task_id, request_data.chat_id, prefetched_diffable_embeds)")


def test_first_turn_overlap_requires_complete_empty_admission_and_no_mentions():
    from types import SimpleNamespace
    from unittest.mock import Mock

    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_can_overlap_first_turn_reads")
    # Replace its production import with a narrow fake that proves the outer
    # first-turn/mention fences independently of the routing implementation.
    helper.body = [node for node in helper.body if not isinstance(node, ast.ImportFrom)]
    module = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"_simple_context_fast_path": Mock(return_value=True),
                 "_stage_one_project_none_candidate": Mock(return_value=False)}
    exec(compile(module, "<first-turn-proof>", "exec"), namespace)
    eligible = namespace["_can_overlap_first_turn_reads"]
    message = SimpleNamespace(role="user", message_id="m1", content="Hello")
    request = SimpleNamespace(chat_has_title=False, message_history=[message], message_id="m1",
                              current_user_content="Hello")
    snapshot = {"routing": {"early_decisions": {"needs_related_work": False}}}
    assert eligible(request, snapshot)
    request.current_user_content = "@mate:coder Hello"
    assert not eligible(request, snapshot)
    request.current_user_content = "Hello"
    request.message_history.append(SimpleNamespace(role="assistant", message_id="m0", content="Hi"))
    assert not eligible(request, snapshot)
    request.message_history.pop()
    request.is_focus_mode_continuation = True
    assert not eligible(request, snapshot)
    request.is_focus_mode_continuation = False
    namespace["_simple_context_fast_path"].return_value = False
    assert not eligible(request, snapshot)


def test_prefetched_embed_lookup_requires_scoped_matching_active_owner():
    import asyncio
    from contextlib import contextmanager
    from contextvars import ContextVar
    from types import SimpleNamespace
    from typing import Optional
    from unittest.mock import AsyncMock, Mock

    source = (Path(__file__).resolve().parents[1] / "processing" / "main_processor.py").read_text()
    tree = ast.parse(source)
    selected = [node for node in tree.body if (
        isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id == "_prefetched_diffable_embeds"
    ) or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
        "_scoped_diffable_embed_prefetch", "_diffable_embeds_for_main_prompt",
    })]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    fallback = AsyncMock(return_value=False)
    namespace = {"ContextVar": ContextVar, "contextmanager": contextmanager,
                 "AskSkillRequest": object, "CacheService": object, "DirectusService": object,
                 "Optional": Optional, "logger": Mock(),
                 "_has_diffable_embeds_for_prompt": fallback}
    exec(compile(module, "<scoped-embed-lookup>", "exec"), namespace)
    scoped = namespace["_scoped_diffable_embed_prefetch"]
    lookup = namespace["_diffable_embeds_for_main_prompt"]

    async def check():
        request = SimpleNamespace(chat_id="chat")
        cache = SimpleNamespace(get_active_ai_task=AsyncMock(return_value="task"))
        with scoped("task", "chat", True):
            assert await lookup("task", request, cache, None, "") is True
            fallback.assert_not_awaited()
            cache.get_active_ai_task.return_value = "newer-task"
            assert await lookup("task", request, cache, None, "") is False
            assert fallback.await_count == 1
        cache.get_active_ai_task.return_value = "task"
        assert await lookup("task", request, cache, None, "") is False
        assert fallback.await_count == 2

    asyncio.run(check())


# contract-test: direct surface=cli assertions=chat-processing-feedback.turn-lifecycle
# A sealed metadata job may run beside provider startup, but a delayed job must
# settle once before visible output or a zero-chunk terminal path proceeds.
def test_first_visible_barrier_waits_once_and_stream_covers_terminal_paths():
    import asyncio
    from typing import Awaitable, Callable, Optional

    source = (Path(__file__).resolve().parents[1] / "tasks" / "stream_consumer.py").read_text()
    tree = ast.parse(source)
    selected = [node for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == "_FirstChunkPublishBarrier"]
    assert len(selected) == 1
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Optional": Optional, "Callable": Callable, "Awaitable": Awaitable}
    exec(compile(module, "<first-visible-barrier>", "exec"), namespace)
    barrier_type = namespace["_FirstChunkPublishBarrier"]

    async def check():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def sealed_notice():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

        barrier = barrier_type(sealed_notice)
        first_chunk = asyncio.create_task(barrier.wait())
        await started.wait()
        assert not first_chunk.done()
        release.set()
        await first_chunk
        await barrier.wait()  # no-chunk terminal / repeated internal frames
        assert calls == 1

    asyncio.run(check())
    consumer = source.split("async def _consume_main_processing_stream(", 1)[1]
    assert "before_first_chunk_publish: Optional[Callable[[], Awaitable[None]]]" in consumer
    assert consumer.count("await first_chunk_barrier.wait()") >= 5
    assert consumer.index("await first_chunk_barrier.wait()", consumer.index("async for chunk in main_processing_stream")) < consumer.index(
        "await content_publisher.flush()", consumer.index("async for chunk in main_processing_stream"))
    assert consumer.index("# A zero-chunk or failed stream still joins before terminal output.") < consumer.index(
        'with ai_phase_span("main.response_finalize")')
