"""The async batch resumes only after every original tool job is terminal."""

import json
import time
import importlib.util
import sys
import base64
import random
from types import SimpleNamespace
from pathlib import Path

import pytest

module_path = Path(__file__).resolve().parents[1] / "apps" / "ai" / "tasks" / "same_turn_skill_barrier.py"
spec = importlib.util.spec_from_file_location("same_turn_skill_barrier_under_test", module_path)
barrier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(barrier)
claim_ready = barrier.claim_ready
record_terminal = barrier.record_terminal
register_barrier = barrier.register_barrier
arm_barrier = barrier.arm_barrier
restore_ordered_tool_results = barrier.restore_ordered_tool_results


LOGICAL = "018f2222-2222-7222-8222-222222222222"


class FakeRedis:
    def __init__(self, values):
        self.values = values

    async def set(self, key, value, *, nx, ex):
        if nx and key in self.values:
            return False
        self.values[key] = json.loads(value) if value.startswith("{") else value
        return True


class FakeCache:
    def __init__(self):
        self.values = {}
        self.redis = FakeRedis(self.values)

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ttl):
        self.values[key] = value
        return True


class JsonDecodingCache(FakeCache):
    """Mirror CacheService.get(), which JSON-decodes Redis scalar strings."""

    async def get(self, key):
        value = await super().get(key)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value


class RawRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, nx, ex):
        if nx and key in self.values:
            return False
        self.values[key] = value.encode() if isinstance(value, str) else value
        return True

    async def setex(self, key, ttl, value):
        self.values[key] = value.encode() if isinstance(value, str) else value
        return True


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.complete-result-barrier
async def test_barrier_uses_real_cache_service_json_scalar_decoding():
    from backend.core.api.app.services.cache_base import CacheServiceBase

    class CacheWithMemoryRedis(CacheServiceBase):
        def __init__(self):
            self.memory_redis = RawRedis()
            self.DEFAULT_TTL = 3600

        @property
        async def client(self):
            return self.memory_redis

    cache = CacheWithMemoryRedis()
    await cache.set("async_skill_latest_user_turn:user:chat", "turn", ttl=60)
    await register_barrier(cache, batch_id="batch", user_id="user", chat_id="chat",
                           turn_id="turn", task_ids=["job"], checkpoint_ref="sealed",
                           deadline=time.time() + 60, logical_task_id=LOGICAL,
                           source_delivery_task_id=LOGICAL)
    await arm_barrier(cache, "batch")
    await record_terminal(cache, batch_id="batch", task_id="job",
                          payload_ref="sealed-result", status="finished")
    assert await cache.get(barrier._key("batch", "armed")) == "armed"
    assert (await claim_ready(cache, batch_id="batch"))["slots"][0]["status"] == "finished"
    cache.memory_redis.values[barrier._key("batch", "armed")] = b"1"
    assert await cache.get(barrier._key("batch", "armed")) == 1
    assert await barrier.barrier_is_armed(cache, "batch")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.complete-result-barrier,app-skills.assistant.idempotent-resume
async def test_json_decoded_armed_marker_resumes_and_accepts_existing_numeric_marker():
    cache = JsonDecodingCache()
    cache.values["async_skill_latest_user_turn:user:chat"] = "turn"
    await register_barrier(cache, batch_id="batch", user_id="user", chat_id="chat",
                           turn_id="turn", task_ids=["job"], checkpoint_ref="sealed",
                           deadline=time.time() + 60, logical_task_id=LOGICAL,
                           source_delivery_task_id=LOGICAL)
    await record_terminal(cache, batch_id="batch", task_id="job",
                          payload_ref="sealed-result", status="finished")
    assert await claim_ready(cache, batch_id="batch") is None
    await arm_barrier(cache, "batch")
    assert (await claim_ready(cache, batch_id="batch"))["slots"][0]["payload_ref"] == "sealed-result"

    # An already-paused turn deployed with the former numeric marker also resumes.
    cache.values[barrier._key("batch", "armed")] = "1"
    assert await barrier.barrier_is_armed(cache, "batch")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.complete-result-barrier,app-skills.assistant.idempotent-resume
async def test_three_jobs_wait_for_all_terminals_in_original_order():
    cache = FakeCache()
    cache.values["async_skill_latest_user_turn:user:chat"] = "turn"
    await register_barrier(cache, batch_id="batch", user_id="user", chat_id="chat",
                           turn_id="turn", task_ids=["a", "b", "c"],
                           checkpoint_ref="sealed", deadline=time.time() + 60,
                           logical_task_id=LOGICAL, source_delivery_task_id=LOGICAL)
    assert await claim_ready(cache, batch_id="batch") is None
    await arm_barrier(cache, "batch")
    await record_terminal(cache, batch_id="batch", task_id="c", payload_ref="ref-c", status="finished")
    await record_terminal(cache, batch_id="batch", task_id="a", payload_ref="ref-a", status="finished")
    assert await claim_ready(cache, batch_id="batch") is None
    await record_terminal(cache, batch_id="batch", task_id="b", payload_ref="ref-b", status="failed")
    assert not await record_terminal(cache, batch_id="batch", task_id="b", payload_ref="retry", status="finished")
    ready = await claim_ready(cache, batch_id="batch")
    assert [slot["task_id"] for slot in ready["slots"]] == ["a", "b", "c"]
    assert [slot["status"] for slot in ready["slots"]] == ["finished", "failed", "finished"]
    assert (await claim_ready(cache, batch_id="batch"))["resume_task_id"] == ready["resume_task_id"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.complete-result-barrier,app-skills.assistant.bounded-private-failure
async def test_deadline_settles_only_missing_slots_and_new_turn_fences_resume(monkeypatch):
    cache = FakeCache()
    cache.values["async_skill_latest_user_turn:user:chat"] = "turn"
    await register_barrier(cache, batch_id="batch", user_id="user", chat_id="chat",
                           turn_id="turn", task_ids=["a", "b", "c"],
                           checkpoint_ref="sealed", deadline=time.time() + 0.01,
                           logical_task_id=LOGICAL, source_delivery_task_id=LOGICAL)
    await arm_barrier(cache, "batch")
    await record_terminal(cache, batch_id="batch", task_id="b", payload_ref="ref-b", status="finished")
    monkeypatch.setattr(barrier.time, "time", lambda: 10**12)
    ready = await claim_ready(cache, batch_id="batch", expire_missing=True)
    assert [slot["status"] for slot in ready["slots"]] == ["timed_out", "finished", "timed_out"]
    cache.values["async_skill_latest_user_turn:user:chat"] = "new-turn"
    assert await claim_ready(cache, batch_id="batch") is None


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.same-turn-completion
async def test_resume_restores_provider_tool_ids_without_a_user_message(monkeypatch):
    async def restore(payload):
        return {"async_tool_completion": {
            "status": "finished", "results": [{"embed_ref": "generated_asset"}],
        }}

    private_module = SimpleNamespace(restore_private_context_payload=restore)
    sanitize_module = SimpleNamespace(sanitize_text_payload_for_ascii_smuggling=lambda value: (value, {}))
    monkeypatch.setitem(sys.modules, "backend.shared.python_utils.recent_work_summary_client", private_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.text_sanitization", sanitize_module)
    request = SimpleNamespace(user_id="user", chat_id="chat", message_id="turn",
                              same_turn_slots=[{"task_id": "a", "status": "finished", "payload_ref": "ref"}])
    checkpoint = {"jobs": [{"task_id": "a", "tool_call_id": "call-7"}],
                  "current_message_history": [
                      {"role": "assistant", "tool_calls": [{"id": "call-7"}]},
                      {"role": "tool", "tool_call_id": "call-7", "name": "images-generate",
                       "content": "processing"},
                  ]}
    history = await restore_ordered_tool_results(request, checkpoint)
    assert [row["role"] for row in history] == ["assistant", "tool"]
    assert history[1]["tool_call_id"] == "call-7"
    assert json.loads(history[1]["content"])["results"][0]["embed_ref"] == "generated_asset"


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.assistant.same-turn-completion
async def test_restored_generated_child_is_trusted_at_final_answer_boundary(monkeypatch):
    child_id = "018f2222-2222-7222-8222-333333333333"
    parent_id = "018f2222-2222-7222-8222-444444444444"
    child_ref = "generated-image-018f22222222"
    parent_ref = "generated-media-images-018f22222222"

    async def restore(payload):
        return {"async_tool_completion": {
            "status": "finished", "request_metadata": {
                "parent_embed_id": parent_id, "parent_embed_ref": parent_ref,
            },
            "results": [{"status": "finished", "child_embed_id": child_id,
                         "embed_ref": child_ref, "parent_embed_id": parent_id,
                         "parent_embed_ref": parent_ref}],
        }}

    monkeypatch.setitem(sys.modules, "backend.shared.python_utils.recent_work_summary_client",
                        SimpleNamespace(restore_private_context_payload=restore))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.text_sanitization",
                        SimpleNamespace(sanitize_text_payload_for_ascii_smuggling=lambda value: (value, {})))
    request = SimpleNamespace(user_id="user", chat_id="chat", message_id="turn",
                              same_turn_slots=[{"task_id": "job", "status": "finished", "payload_ref": "sealed"}])
    checkpoint = {"jobs": [{"task_id": "job", "tool_call_id": "call-7",
                            "app_id": "images", "skill_id": "generate"}],
                  "current_message_history": [{"role": "tool", "tool_call_id": "call-7",
                                               "name": "images-generate", "content": "processing"}]}
    await restore_ordered_tool_results(request, checkpoint)
    from backend.shared.python_utils.generated_media_graph import finalize_trusted_inline_refs
    answer = finalize_trusted_inline_refs(
        "Done. embed:generated-image-018f22222222",
        checkpoint["authored_inline_outputs"],
        required_refs=checkpoint["generated_embed_refs"],
    )
    assert answer.count(f"(embed:{child_ref})") == 1
    assert f"(embed:{parent_ref})" in answer
    assert {row["embed_id"] for row in checkpoint["authored_inline_outputs"]} == {child_id, parent_id}


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
def test_private_checkpoint_round_trips_one_bounded_json_copy():
    request = {"message_history": [{"role": "user", "content": "private " * 2000}],
               "selected_mate_id": "mate-a"}
    checkpoint = {"native_main_cursor": 2,
                  "native_main_snapshot": [{"role": "assistant", "content": "tool call"}],
                  "models_to_try": ["provider/model-a"], "current_model_id": "provider/model-a",
                  "selected_mate_id": "mate-a"}
    packed = barrier.pack_private_checkpoint(request, checkpoint)
    assert "private" not in str(packed)
    restored_request, restored_checkpoint = barrier.unpack_private_checkpoint(packed)
    assert restored_request == request
    assert restored_checkpoint == checkpoint


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
def test_deadline_uses_longest_job_envelope_in_mixed_batch():
    assert barrier.deadline_seconds_for_jobs([
        {"app_id": "web", "skill_id": "search"},
        {"app_id": "images", "skill_id": "vectorize"},
    ]) == 720
    assert barrier.deadline_seconds_for_jobs([
        {"app_id": "images", "skill_id": "generate"},
        {"app_id": "music", "skill_id": "generate", "request_count": 5},
    ]) == 5040
    assert barrier.deadline_seconds_for_jobs([
        {"app_id": "images", "skill_id": "generate", "request_count": 1},
    ]) == 1140


# contract-test: supporting surface=rest_api assertions=app-skills.media.visible-assistant-results
def test_generated_refs_are_preserved_once_even_if_provider_omits_them():
    answer = "I made the image. [First image](embed:generated-images-first)"
    completed = barrier.ensure_generated_refs(
        answer, ["generated-images-first", "generated-images-second", "generated-images-second"],
    )
    assert completed.count("embed:generated-images-first") == 1
    assert completed.count("embed:generated-images-second") == 1
    assert "[Generated result](embed:generated-images-second)" in completed


# contract-test: supporting surface=rest_api assertions=app-skills.media.visible-assistant-results
def test_generated_refs_match_complete_markdown_targets_and_uuid_aliases():
    child_id = "018f3333-3333-7333-8333-333333333333"
    slug = "generated-images-018f33333333"
    aliases = {slug: [child_id]}
    answer = f"Already shown [image](embed:{child_id.replace('-', '')})."
    assert barrier.ensure_generated_refs(answer, [slug], aliases) == answer
    wrong_prefix = f"This is another [image](embed:{slug}-different)."
    completed = barrier.ensure_generated_refs(wrong_prefix, [slug], aliases)
    assert completed.count(f"embed:{slug})") == 1
    assert f"embed:{slug}-different)" in completed
    # Plain prose containing the token is not an actual embed target.
    assert barrier.ensure_generated_refs(f"The token embed:{slug} is mentioned.", [slug], aliases).count(
        f"(embed:{slug})"
    ) == 1


# contract-test: supporting surface=rest_api assertions=app-skills.media.visible-assistant-results
def test_only_authored_successful_children_require_parent_and_child_preview():
    child_id = "018f4444-4444-7444-8444-444444444444"
    parent_id = "018f5555-5555-7555-8555-555555555555"
    parent_ref = "generated-media-images-018f55555555"
    rows = [
        {"status": "finished", "embed_ref": "generated-images-child",
         "child_embed_id": child_id, "parent_embed_ref": parent_ref,
         "parent_embed_id": parent_id},
        {"status": "error", "embed_ref": "fabricated-failure",
         "parent_embed_ref": "fabricated-parent", "parent_embed_id": parent_id},
    ]
    refs, aliases = barrier._generated_ref_bindings(rows, app_id="images")
    assert refs == ["generated-images-child", parent_ref]
    assert aliases == {"generated-images-child": [child_id],
                       parent_ref: [parent_id]}
    answer = f"Here is the first child [image](embed:{child_id})."
    completed = barrier.ensure_generated_refs(answer, refs, aliases)
    assert "(embed:generated-images-child)" not in completed
    assert completed.count(f"(embed:{parent_ref})") == 1
    # A parent supplied only by callback metadata is accepted when a real
    # successful child in the same producer callback proves useful output.
    metadata_refs, _ = barrier._generated_ref_bindings(
        [{"status": "finished", "embed_ref": "generated-images-child",
          "child_embed_id": child_id}], app_id="images",
        metadata={"parent_embed_ref": parent_ref, "parent_embed_id": parent_id},
    )
    assert metadata_refs == ["generated-images-child", parent_ref]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.media.visible-assistant-results,app-skills.assistant.same-turn-completion
async def test_restored_media_completion_carries_authored_parent_and_child_aliases(monkeypatch):
    child_id = "018f6666-6666-7666-8666-666666666666"
    parent_id = "018f7777-7777-7777-8777-777777777777"
    child_ref = "generated-images-018f66666666"
    parent_ref = "generated-media-images-018f77777777"

    async def restore(_payload):
        return {"async_tool_completion": {"status": "finished", "results": [{
            "status": "finished", "embed_ref": child_ref, "child_embed_id": child_id,
            "parent_embed_ref": parent_ref, "parent_embed_id": parent_id,
        }]}}

    monkeypatch.setitem(sys.modules, "backend.shared.python_utils.recent_work_summary_client",
                        SimpleNamespace(restore_private_context_payload=restore))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.text_sanitization",
                        SimpleNamespace(sanitize_text_payload_for_ascii_smuggling=lambda value: (value, {})))
    request = SimpleNamespace(user_id="user", chat_id="chat", message_id="turn", same_turn_slots=[
        {"task_id": "producer", "status": "finished", "payload_ref": "sealed-result"},
    ])
    checkpoint = {"jobs": [{"task_id": "producer", "tool_call_id": "call-1",
                             "app_id": "images", "skill_id": "generate"}],
                  "current_message_history": [{"role": "assistant", "tool_calls": [{"id": "call-1"}]},
                                              {"role": "tool", "tool_call_id": "call-1", "content": "processing"}]}
    history = await restore_ordered_tool_results(request, checkpoint)
    assert json.loads(history[1]["content"])["results"][0]["parent_embed_ref"] == parent_ref
    assert checkpoint["generated_embed_refs"] == [child_ref, parent_ref]
    assert checkpoint["generated_embed_aliases"] == {child_ref: [child_id], parent_ref: [parent_id]}
    answer = f"[Image](embed:{child_id.replace('-', '')}) and [Set](embed:{parent_id})"
    assert barrier.ensure_generated_refs(
        answer, checkpoint["generated_embed_refs"], checkpoint["generated_embed_aliases"],
    ) == answer


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
def test_preflight_rejects_large_private_transcript_before_a_job_is_queued():
    moderate = base64.b64encode(random.Random(7).randbytes(50_000)).decode("ascii")
    large = base64.b64encode(random.Random(8).randbytes(130_000)).decode("ascii")
    barrier.preflight_private_checkpoint_capacity(
        {"message_history": [{"role": "user", "content": moderate}]},
        [{"role": "user", "content": moderate}], None, None, None,
    )
    # The full encrypted handoff still allows this size, but preflight keeps
    # headroom for the provider/native state and later same-batch sync results.
    barrier.pack_private_checkpoint({"message_history": []}, {
        "current_message_history": [{"role": "user", "content": large}],
    })
    with pytest.raises(RuntimeError, match="headroom"):
        barrier.preflight_private_checkpoint_capacity(
            {"message_history": []}, [{"role": "user", "content": large}],
            None, None, None,
        )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.same-turn-completion,app-skills.assistant.complete-result-barrier
async def test_native_multi_tool_transcript_keeps_sync_result_and_async_identity(monkeypatch):
    async def restore(payload):
        return {"async_tool_completion": {
            "status": "finished", "results": [{"embed_ref": f"image-{payload['agentic_context_request_id']}"}],
        }}

    monkeypatch.setitem(sys.modules, "backend.shared.python_utils.recent_work_summary_client",
                        SimpleNamespace(restore_private_context_payload=restore))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.text_sanitization",
                        SimpleNamespace(sanitize_text_payload_for_ascii_smuggling=lambda value: (value, {})))
    native_calls = [{"id": "call-image-a"}, {"id": "call-web"}, {"id": "call-image-b"}]
    checkpoint = {
        "native_main_cursor": 3,
        "native_main_snapshot": [{"role": "assistant", "tool_calls": native_calls}],
        "models_to_try": ["provider/exact-model"],
        "current_model_id": "provider/exact-model",
        "selected_mate_id": "mate-exact",
        "jobs": [
            {"task_id": "a", "tool_call_id": "call-image-a", "app_id": "images", "skill_id": "generate"},
            {"task_id": "b", "tool_call_id": "call-image-b", "app_id": "images", "skill_id": "generate"},
        ],
        "current_message_history": [
            {"role": "user", "content": "Make two images and find context."},
            {"role": "assistant", "tool_calls": native_calls},
            {"role": "tool", "tool_call_id": "call-image-a", "content": "processing"},
            {"role": "tool", "tool_call_id": "call-web", "content": "Verified web evidence"},
            {"role": "tool", "tool_call_id": "call-image-b", "content": "processing"},
        ],
    }
    request = SimpleNamespace(user_id="user", chat_id="chat", message_id="turn", same_turn_slots=[
        {"task_id": "a", "status": "finished", "payload_ref": "ref-a"},
        {"task_id": "b", "status": "finished", "payload_ref": "ref-b"},
    ])
    history = await restore_ordered_tool_results(request, checkpoint)
    assert [row["role"] for row in history] == ["user", "assistant", "tool", "tool", "tool"]
    assert history[1]["tool_calls"] == checkpoint["native_main_snapshot"][0]["tool_calls"]
    assert history[3]["content"] == "Verified web evidence"
    assert [history[index]["tool_call_id"] for index in (2, 4)] == ["call-image-a", "call-image-b"]
    assert [json.loads(history[index]["content"])["results"][0]["embed_ref"]
            for index in (2, 4)] == ["image-a", "image-b"]
    assert checkpoint["generated_embed_refs"] == ["image-a", "image-b"]
    assert barrier.ensure_generated_refs("Two images are ready.", checkpoint["generated_embed_refs"]).count("embed:") == 2


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.same-turn-completion,app-skills.assistant.bounded-private-failure
def test_resume_rejects_changed_model_or_mate_instead_of_rerouting():
    checkpoint = {"models_to_try": ["provider/exact", "provider/fallback"],
                  "current_model_index": 0, "current_model_id": "provider/exact",
                  "selected_mate_id": "mate-original"}
    assert barrier.selected_resume_route(
        checkpoint, ["provider/exact", "provider/fallback"], "mate-original",
    ) == (0, "provider/exact")
    with pytest.raises(RuntimeError, match="model or mate"):
        barrier.selected_resume_route(checkpoint, ["provider/changed"], "mate-original")
    with pytest.raises(RuntimeError, match="model or mate"):
        barrier.selected_resume_route(
            checkpoint, ["provider/exact", "provider/fallback"], "mate-new",
        )
