"""The registered generation task seals one parent around ordered output children."""

from types import SimpleNamespace
from types import ModuleType
from unittest.mock import AsyncMock
import sys
import uuid

import pytest

from backend.shared.python_utils.generated_media_graph import (
    collect_authored_skill_output_bindings,
    finalize_trusted_inline_refs,
    run_generated_media_batch,
    send_generated_media_child,
)


# contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
@pytest.mark.asyncio
async def test_media_batch_seals_successful_children_and_notifies_once_after_parent(monkeypatch):
    parent_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    sent = []
    callback = AsyncMock()

    class FakeEmbedService:
        def __init__(self, *_args):
            pass

        @staticmethod
        def _registered_child_embed_id(embed_id, index):
            return str(uuid.uuid5(uuid.UUID(embed_id), f"embed-child:{index}"))

        async def send_embed_data_to_client(self, **kwargs):
            sent.append(kwargs)
            return True

    embed_service_module = ModuleType("backend.core.api.app.services.embed_service")
    embed_service_module.EmbedService = FakeEmbedService
    monkeypatch.setitem(sys.modules, embed_service_module.__name__, embed_service_module)
    continuation_module = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation_module.dispatch_async_skill_continuation = callback
    monkeypatch.setitem(sys.modules, continuation_module.__name__, continuation_module)

    class FakeTask:
        request = SimpleNamespace(id=task_id)
        _cache_service = object()
        _directus_service = object()
        _encryption_service = object()

        async def initialize_core_services(self):
            pass

        async def cleanup_services(self):
            pass

    async def generate_one(_task, app_id, _skill_id, child_args):
        if child_args["media_child_index"] == 1:
            raise RuntimeError("provider detail must stay private")
        child_id = child_args["embed_id"]
        await send_generated_media_child(
            FakeEmbedService(), parent_embed_id=child_args["producer_embed_id"],
            child_embed_id=child_id, child_index=child_args["media_child_index"],
            content={"app_id": app_id, "prompt": child_args["prompt"], "model": "actual-model"},
            chat_id="chat", message_id="message", user_id="user", user_id_hash="hash",
            created_at=1, log_prefix="[test]",
        )
        return {
            "status": "finished", "embed_id": child_id,
            "prompt": child_args["prompt"], "model": "actual-model",
            "aes_key": "secret", "files": {"original": {"download_url": "signed-token"}},
        }

    result = await run_generated_media_batch(
        FakeTask(), app_id="images", skill_id="generate",
        arguments={
            "embed_id": parent_id, "user_id": "user", "chat_id": "chat", "message_id": "message",
            "requests": [{"prompt": "first"}, {"prompt": "second"}, {"prompt": "third"}],
        },
        generate_one=generate_one,
    )

    expected_children = [FakeEmbedService._registered_child_embed_id(parent_id, index) for index in (0, 2)]
    assert result["child_embed_ids"] == expected_children
    assert [item["embed_id"] for item in sent] == [*expected_children, parent_id]
    assert sent[-1]["embed_ids"] == expected_children
    assert sent[-1]["content_toon"]
    assert [item["subject_id"] for item in sent[-1]["producer_final_children"]] == expected_children
    callback.assert_awaited_once()
    callback_args = callback.await_args.kwargs
    assert callback_args["async_task_id"] == task_id
    assert callback_args["result_status"] == "failed"
    assert [row["request_index"] for row in callback_args["completed_results"]] == [0, 1, 2]
    assert callback_args["completed_results"][0]["embed_ref"]
    assert callback_args["completed_results"][0]["parent_embed_id"] == parent_id
    assert callback_args["completed_results"][0]["parent_embed_ref"].startswith("generated-media-images-")
    assert callback_args["request_metadata"]["parent_embed_id"] == parent_id
    assert callback_args["request_metadata"]["parent_embed_ref"] == callback_args["completed_results"][0]["parent_embed_ref"]
    assert "aes_key" not in callback_args["completed_results"][0]
    assert "files" not in callback_args["completed_results"][0]
    assert callback_args["completed_results"][1] == {
        "parent_embed_id": parent_id,
        "parent_embed_ref": callback_args["completed_results"][0]["parent_embed_ref"],
        "request_index": 1, "status": "error", "error": "Generation failed",
    }


# contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
@pytest.mark.asyncio
async def test_standalone_media_child_never_self_parents():
    sent = []

    class FakeEmbedService:
        async def send_embed_data_to_client(self, **kwargs):
            sent.append(kwargs)

    embed_id = str(uuid.uuid4())
    await send_generated_media_child(
        FakeEmbedService(), parent_embed_id=embed_id, child_embed_id=embed_id,
        child_index=0, content={"app_id": "images", "prompt": "a bird", "model": "actual-model"},
        chat_id="chat", message_id="message", user_id="user", user_id_hash="hash",
        created_at=1, log_prefix="[test]",
    )
    assert sent[0]["parent_embed_id"] is None
    assert sent[0]["embed_id"] == embed_id


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_search_refs_require_matching_authored_child_ids():
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    results = [
        {"embed_ref": "spicy-chickpea-freekeh-n9J", "title": "Spicy Chickpea Freekeh"},
        {"embed_ref": "lemon-soup-r2D", "title": "Lemon Soup"},
    ]
    bindings = collect_authored_skill_output_bindings(
        app_id="nutrition", skill_id="search_recipes", results=results,
        authored_embeds=[{"status": "finished", "child_embed_ids": [first, second]}],
    )
    assert [row["embed_id"] for row in bindings] == [first, second]
    assert [row["embed_ref"] for row in bindings] == [row["embed_ref"] for row in results]
    assert collect_authored_skill_output_bindings(
        app_id="nutrition", skill_id="search_recipes", results=results,
        authored_embeds=[{"status": "error", "child_embed_ids": [first, second]}],
    ) == []
    assert collect_authored_skill_output_bindings(
        app_id="nutrition", skill_id="search_recipes", results=results,
        authored_embeds=[{"child_embed_ids": [first]}],
    ) == []


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_selected_bare_recipe_refs_become_large_cards_without_inventing_candidates():
    first, second, unselected = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    rows = [
        {"app_id": "nutrition", "skill_id": "search_recipes", "status": "finished",
         "embed_ref": ref, "embed_id": identity, "title": title}
        for ref, identity, title in [
            ("spicy-chickpea-freekeh-n9J", first, "Spicy Chickpea Freekeh"),
            ("lemon-soup-r2D", second, "Lemon Soup"),
            ("third-recipe-v3K", unselected, "Third Recipe"),
        ]
    ]
    answer = "Try these:\nembed:spicy-chickpea-freekeh-n9J\nembed:lemon-soup-r2D"
    finalized = finalize_trusted_inline_refs(answer, rows)
    assert "[!](embed:spicy-chickpea-freekeh-n9J)" in finalized
    assert "[!](embed:lemon-soup-r2D)" in finalized
    assert "third-recipe-v3K" not in finalized
    assert finalize_trusted_inline_refs(finalized, rows) == finalized


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_ref_finalizer_dedups_uuid_slug_and_existing_markdown():
    identity = str(uuid.uuid4())
    row = {"app_id": "design", "skill_id": "search_icons", "status": "finished",
           "embed_ref": "home-icon-n9J", "embed_id": identity, "title": "Home Icon"}
    answer = f"[Home](embed:{identity})\nembed:home-icon-n9J\nembed:{identity}"
    finalized = finalize_trusted_inline_refs(answer, [row])
    assert finalized.count("[!](embed:home-icon-n9J)") == 0
    assert finalized.count("(embed:") == 1
    assert "[Home](embed:home-icon-n9J)" in finalized
    assert "embed:" not in finalized.splitlines()[1]


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_unique_authored_slug_repairs_a_wrong_random_suffix_without_guessing():
    row = {"app_id": "design", "skill_id": "search_icons", "status": "finished",
           "embed_ref": "home-outline-rounded-OcB", "embed_id": str(uuid.uuid4()),
           "title": "Home Outline Rounded"}
    answer = "[Home icon](embed:home-outline-rounded-Cy4)"
    assert finalize_trusted_inline_refs(answer, [row]) == "[Home icon](embed:home-outline-rounded-OcB)"
    assert finalize_trusted_inline_refs("embed:home-outline-rounded-Cy4", [row]) == (
        "[!](embed:home-outline-rounded-OcB)"
    )


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_ambiguous_slug_cannot_fabricate_a_result_link():
    rows = [
        {"app_id": "design", "skill_id": "search_icons", "status": "finished",
         "embed_ref": f"home-outline-rounded-{suffix}", "embed_id": str(uuid.uuid4()),
         "title": "Home Outline Rounded"}
        for suffix in ("OcB", "Kz4")
    ]
    assert finalize_trusted_inline_refs(
        "[Home icon](embed:home-outline-rounded-Cy4)", rows,
        include_named_search_results=False,
    ) == "Home icon"
    assert finalize_trusted_inline_refs(
        "embed:home-outline-rounded-Cy4", rows,
        include_named_search_results=False,
    ) == "result unavailable"
    assert finalize_trusted_inline_refs(
        "[Home Outline Rounded](embed:home-outline-rounded-Cy4)", rows,
    ) == "Home Outline Rounded"


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_ref_finalizer_ignores_unknown_failed_and_code_tokens():
    identity = str(uuid.uuid4())
    row = {"app_id": "design", "skill_id": "search_icons", "status": "finished",
           "embed_ref": "home-icon-n9J", "embed_id": identity, "title": "Home Icon"}
    failed = {**row, "status": "failed", "embed_ref": "failed-icon-r2D", "embed_id": str(uuid.uuid4())}
    answer = "`embed:home-icon-n9J`\n```text\nembed:home-icon-n9J\n```\nembed:made-up-x9Z\nembed:failed-icon-r2D"
    assert finalize_trusted_inline_refs(answer, [row, failed]) == answer


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_named_search_results_use_bounded_whole_title_matches():
    rows = [
        {"app_id": "design", "skill_id": "search_icons", "status": "finished",
         "embed_ref": f"icon-{name.lower()}-{index}", "embed_id": str(uuid.uuid4()), "title": name}
        for index, name in enumerate(["Home", "Search", "Bell", "Heart", "Moon"], start=1)
    ]
    answer = "Use Search, Bell, Heart, and Moon icons in this homework screen."
    finalized = finalize_trusted_inline_refs(answer, rows)
    assert "icon-home-1" not in finalized
    assert finalized.count("[!](embed:") == 3
    assert "icon-search-2" in finalized
    assert "icon-bell-3" in finalized
    assert "icon-heart-4" in finalized
    assert "icon-moon-5" not in finalized
    assert finalize_trusted_inline_refs("embed:homework-x9Y", rows) == "embed:homework-x9Y"


# contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
def test_required_generated_output_is_appended_once_using_authored_identity():
    child_id = str(uuid.uuid4())
    row = {"app_id": "images", "skill_id": "generate", "status": "finished",
           "embed_ref": "generated-images-f471ad31c584", "embed_id": child_id}
    answer = finalize_trusted_inline_refs("Here is the image.", [row], required_refs=[child_id])
    assert answer.endswith("[!](embed:generated-images-f471ad31c584)")
    assert finalize_trusted_inline_refs(answer, [row], required_refs=[row["embed_ref"]]) == answer
    assert finalize_trusted_inline_refs("Here is the image.", [row], required_refs=["made-up-ref"]) == (
        "Here is the image."
    )
