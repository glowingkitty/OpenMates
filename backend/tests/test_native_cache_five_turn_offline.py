# contract-test-file: infrastructure
# contract-test: supporting surface=gui.web assertions=billing.usage.receipt-token-breakdown
"""Offline five-turn native replay through the real processor and signed mock gate."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.apps.ai.processing import main_processor
from backend.apps.ai.processing.model_usage_tracker import calculate_model_usage_credits
from backend.apps.ai.processing.native_history_cache import (
    finalize_native_cache_state,
    seal_native_embed_fingerprints,
)
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.testing import native_cache_tools_fixture
from backend.apps.ai.testing.native_cache_tools_fixture import PROMPTS
from backend.apps.ai.utils import llm_utils
from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode


class _HistoryMessage(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def model_dump(self, **_kwargs):
        return dict(self)


class _NoCassetteCache:
    def fingerprint_llm_call(self, **_kwargs):
        return "offline-native-five-turn"

    def load(self, *_args):
        return None


class _MemoryWalletAndEmbeds:
    def __init__(self):
        self.credits = 1000
        self.embeds: dict[str, dict] = {}
        self.charges: dict[str, dict] = {}

    async def get_pending_app_settings_memories_request(self, _chat_id):
        return None

    async def get_user_by_id(self, _user_id):
        return {"credits": self.credits}

    async def get_embed_from_cache(self, embed_id):
        return copy.deepcopy(self.embeds.get(embed_id))

    async def get(self, _key):
        return None

    async def publish_event(self, *_args, **_kwargs):
        return None

    @property
    def client(self):
        async def no_redis():
            return None
        return no_redis()

    def settle(self, charge_id: str, usage: dict) -> None:
        assert charge_id not in self.charges
        assert usage["total_input_tokens"] > 0
        assert usage["total_output_tokens"] > 0
        charged = calculate_model_usage_credits(
            usage["usage_by_model"], main_processor.config_manager.get_model_pricing,
        )
        assert charged > 0
        self.credits -= charged
        self.charges[charge_id] = {"credits": charged, "usage": copy.deepcopy(usage)}


class _MemoryVault:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def encrypt_with_user_key(self, plaintext, key_id):
        ciphertext = f"vault:v1:offline:{len(self.values) + 1}"
        self.values[ciphertext] = plaintext
        return ciphertext, key_id

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return self.values[ciphertext]


def _request(turn: int, history: list[dict]) -> SimpleNamespace:
    request = SimpleNamespace(
        chat_id="native-offline-chat", message_id=f"user-{turn}",
        user_id="native-offline-user", user_id_hash="native-offline-user-hash",
        user_preferences={}, mentioned_settings_memories_cleartext=None,
        historical_artifact_context=None, current_user_content=PROMPTS[turn],
        active_focus_id=None, active_project_focus=None, current_project=None,
        current_chat_title="Synthetic Square Roots", is_incognito=False,
        is_external=False, message_history=history, orchestration_id=None,
        is_sub_chat=False, is_sub_chat_continuation=False,
        awaiting_async_skill_continuation=False, mate_id="mate-1",
        chat_has_title=True, chat_key_version=1, parent_id=None,
        root_chat_id=None, root_turn_id=None, sub_chat_depth=0,
        orchestration_dispatch_token=None, orchestration_descendant_limit=None,
        orchestration_credit_limit=None, orchestration_approved=False,
        budget_limit=None, budget_spent=0, team_id=None, team_id_hash=None,
        team_workspace_type=None, team_object_id_hash=None,
        recovery_preflight_id=None, recovery_turn_id=None,
        recovery_public_key=None, learning_mode=None, client_capabilities=[],
        is_anonymous=False, anonymous_reservation_id=None,
        has_image_upload_embed=False, embed_file_path_index=None,
    )
    request.resolved_recovery_inference_task_id = lambda: None
    request.model_dump = lambda **_kwargs: request.__dict__.copy()
    return request


def _preprocessing(selected_skills: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        load_app_settings_and_memories=[], rejection_reason=None,
        relevant_app_skills=selected_skills,
        selected_main_llm_model_id="openai/gpt-6.1-sol",
        selected_main_llm_model_name="GPT-6.1 Sol",
        selected_secondary_model_id=None, selected_fallback_model_id=None,
        selected_mate_id="mate-1", category="general", output_language="en",
        relevant_embedded_previews=[], relevant_focus_modes=[],
        enable_subchats=False, ai_model_topics=[], llm_response_temp=0.4,
        user_requested_skills_only=False, user_requested_focus_only=False,
    )


async def _run_offline(monkeypatch, *, drop_frame_turn: int | None = None):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    # ConfigManager's default /app/backend/providers path exists in Docker only.
    # Load the same checked-in tariff metadata for this host-side offline proof.
    providers_dir = Path(__file__).resolve().parents[1] / "providers"
    provider_configs = {
        provider: yaml.safe_load((providers_dir / f"{provider}.yml").read_text())
        for provider in ("google", "openai")
    }
    monkeypatch.setattr(main_processor.config_manager, "_provider_configs", provider_configs)
    wallet = _MemoryWalletAndEmbeds()
    vault = _MemoryVault()
    async def forbidden_provider(**_kwargs):
        raise AssertionError("Real provider dispatch is forbidden")
    signed_provider = wrap_provider_with_cache(forbidden_provider, _NoCassetteCache())
    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "google", signed_provider)
    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "google_ai_studio", signed_provider)
    class NoHealthCache:
        @property
        def client(self):
            async def no_redis():
                return None
            return no_redis()
    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)
    native_calls: list[dict] = []
    original_fixture = native_cache_tools_fixture.generate_fixture

    def observed_fixture(category, kwargs):
        result = original_fixture(category, kwargs)
        if category == "llm/gpt-6.1-sol":
            context = kwargs.get("native_cache_context")
            messages = context["messages"] if isinstance(context, dict) else []
            if (drop_frame_turn is not None and result is not None
                    and PROMPTS[drop_frame_turn] in str(messages[-1].get("content", ""))
                    and result["response"]["chunks"][0].get("kind") == "text"):
                result["response"]["chunks"] = [
                    chunk for chunk in result["response"]["chunks"]
                    if chunk.get("class") != "NativeCacheProviderOutput"
                ]
            chunks = result["response"]["chunks"] if result else []
            reported_usage = [chunk["value"] for chunk in chunks
                              if chunk.get("class") == "OpenAIUsageMetadata"]
            native_calls.append({
                "matched": result is not None,
                "native": isinstance(context, dict),
                "messages": len(messages),
                "stable_prefix_sha256": hashlib.sha256(
                    str(messages[0].get("content", "")).encode("utf-8")
                ).hexdigest() if messages else None,
                "cache_read": reported_usage[0]["cache_read_input_tokens"] if reported_usage else None,
                "cache_write": reported_usage[0]["cache_creation_input_tokens"] if reported_usage else None,
                "paired_call_result_tail": (
                    len(messages) >= 2
                    and messages[-2].get("role") == "assistant"
                    and messages[-1].get("role") == "tool"
                    and messages[-1].get("tool_call_id") == "native-fixture-call"
                ),
                "active_tools": sorted(tool["function"]["name"] for tool in
                                       (context.get("active_tools") or [])) if isinstance(context, dict) else [],
                "baseline_tools": sorted(tool["function"]["name"] for tool in
                                         (context.get("baseline_tools") or [])) if isinstance(context, dict) else [],
                "private_prior_outputs": sum(
                    1 for message in context["messages"]
                    if message.get("role") == "assistant" and
                    isinstance(message.get("provider_transport_state"), list)
                ) if isinstance(context, dict) else 0,
            })
        return result
    monkeypatch.setattr(native_cache_tools_fixture, "generate_fixture", observed_fixture)
    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "openai", signed_provider)
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _model: [])
    monkeypatch.setattr(main_processor, "resolve_sub_chat_depth", lambda _request: 0)
    monkeypatch.setattr(main_processor, "has_transcribed_web_audio_recording", lambda _history: False)
    monkeypatch.setattr(main_processor, "should_include_embeds_results_view_instruction", lambda *_a, **_k: False)
    monkeypatch.setattr(main_processor, "normalize_wikipedia_language", lambda language: language)
    monkeypatch.setattr(main_processor, "TranslationService", lambda: SimpleNamespace(get_nested_translation=lambda *_a, **_k: None))
    monkeypatch.setattr(main_processor, "model_history_token_budget", lambda *_a, **_k: 100_000)
    monkeypatch.setattr(main_processor, "truncate_message_history_to_token_budget", lambda history, **_k: history)
    async def no_task_queue_retry(*_args, **_kwargs):
        return None
    monkeypatch.setattr(main_processor, "evaluate_task_queue_post_turn", no_task_queue_retry)
    tool = {"type": "function", "function": {"name": "math-calculate", "description": "Calculate", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}}}}
    monkeypatch.setattr(main_processor, "generate_tools_from_apps", lambda **kwargs: [tool] if "math-calculate" in (kwargs.get("preselected_skills") or []) else [])
    async def empty_preview(**_kwargs):
        return {}
    monkeypatch.setattr(main_processor, "_resolve_skill_preview_metadata", empty_preview)

    async def execute_math(**kwargs):
        expression = kwargs["arguments"]["expression"]
        assert expression in {"sqrt(144)", "sqrt(169)"}
        return [{"status": "success", "result": "12" if expression == "sqrt(144)" else "13"}]
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute_math)

    async def no_skill_hold(**_kwargs):
        return []
    monkeypatch.setattr(main_processor, "_reserve_skill_credits", no_skill_hold)

    async def charge_math(**kwargs):
        assert kwargs["app_id"] == "math" and kwargs["skill_id"] == "calculate"
        charge_id = f"math-calculate:{kwargs['task_id']}"
        assert charge_id not in wallet.charges
        wallet.credits -= 1
        wallet.charges[charge_id] = {"credits": 1, "usage": "fixed_skill"}
    monkeypatch.setattr(main_processor, "_charge_skill_credits", charge_math)

    class FakeEmbedService:
        def __init__(self, **_kwargs):
            pass

        @staticmethod
        async def get_child_embed_type(*_args, **_kwargs):
            return "math_result"

        @staticmethod
        def _generate_embed_ref_slug(_child_type, _result):
            return "math-result"

        @staticmethod
        def _unique_embed_ref(raw, _seen):
            return raw

        @staticmethod
        def _sanitize_request_metadata(arguments):
            return arguments

        async def create_processing_embed_placeholder(self, **kwargs):
            embed_id = f"embed-{kwargs['message_id']}"
            reference = json.dumps({"type": "app_skill_use", "embed_id": embed_id,
                                    "app_id": kwargs["app_id"], "skill_id": kwargs["skill_id"]},
                                   separators=(",", ":"))
            return {"embed_id": embed_id, "embed_reference": reference, "status": "processing"}

        async def update_embed_with_results(self, **kwargs):
            embed_id = kwargs["embed_id"]
            wallet.embeds[embed_id] = {
                "embed_id": embed_id, "type": "app_skill_use", "status": "finished",
                "hashed_user_id": kwargs["user_id_hash"],
                "encrypted_content": f"vault:v1:embed:{embed_id}",
            }
            return {"embed_id": embed_id, "status": "finished"}

    from backend.core.api.app.services import embed_service
    monkeypatch.setattr(embed_service, "EmbedService", FakeEmbedService)

    history: list[dict] = []
    previous_state = None
    activate_mock_mode("mock", "native_cache_tools_v1", task_id="native-offline-five-turn")
    try:
        for turn in range(1, 6):
            history.append(_HistoryMessage(role="user", message_id=f"user-{turn}", content=PROMPTS[turn]))
            pre = await llm_utils.call_preprocessing_llm(
                task_id=f"native-offline-{turn}:pre",
                model_id="google/gemini-3.5-flash-lite",
                message_history=[{"role": "user", "content": PROMPTS[turn]}],
                tool_definition={"type": "function", "function": {
                    "name": "analyze_request_properties", "description": "Classify request",
                    "parameters": {"type": "object", "properties": {}},
                }},
                allow_retries=False,
            )
            assert pre.error_message is None, turn
            selected_skills = pre.arguments["relevant_app_skills"]
            assert selected_skills == (["math-calculate"] if turn in {1, 3} else []), turn
            assert (pre.arguments["task_area"] == "math") is (turn in {1, 3}), turn
            request = _request(turn, copy.deepcopy(history))
            if previous_state is not None:
                ciphertext, _ = await vault.encrypt_with_user_key(json.dumps(previous_state), "offline-key")
                request.message_history[-2]["encrypted_native_cache_context"] = ciphertext
            output = [chunk async for chunk in main_processor.handle_main_processing(
                f"native-offline-{turn}", request, _preprocessing(selected_skills),
                {"base_ethics_instruction": "Stable provider instruction."},
                SimpleNamespace(), vault, "offline-key", [],
                discovered_apps_metadata={"math": SimpleNamespace(
                    skills=[SimpleNamespace(id="calculate", tool_schema={"type": "object", "properties": {"expression": {"type": "string"}}}, exclude_fields_for_llm=[])],
                    instructions=[],
                )},
                cache_service=wallet,
                user_overrides=SimpleNamespace(skills=None, wikipedia_references=[]),
            )]
            failures = [x for x in output if isinstance(x, dict) and x.get("__main_processing_failure__")]
            assert not failures, (turn, failures)
            visible = "".join(x for x in output if isinstance(x, str))
            assert visible and "error" not in visible.lower(), (turn, len(visible))
            usage = next(x for x in output if isinstance(x, dict) and x.get("__cumulative_llm_usage__"))
            wallet.settle(f"ai-ask:native-offline-{turn}:main", usage)
            post = await llm_utils.call_preprocessing_llm(
                task_id=f"native-offline-{turn}:post",
                model_id="google/gemini-3.5-flash-lite",
                message_history=[{"role": "user", "content": PROMPTS[turn]},
                                 {"role": "assistant", "content": visible}],
                tool_definition={"type": "function", "function": {
                    "name": "generate_suggestions_and_metadata", "description": "Suggest followups",
                    "parameters": {"type": "object", "properties": {}},
                }},
                allow_retries=False,
            )
            assert post.error_message is None and post.arguments["updated_chat_title"], turn
            if turn == drop_frame_turn:
                assert not any(isinstance(x, dict) and x.get("__native_cache_context__") for x in output)
                assert usage["successful_model_id"] == "openai/gpt-6.1-sol"
                return
            native = next(x for x in output if isinstance(x, dict) and x.get("__native_cache_context__"))
            tool_info = next((x["__tool_calls_info__"] for x in output if isinstance(x, dict) and "__tool_calls_info__" in x), [])
            if turn in {1, 3}:
                assert len(tool_info) == 1 and tool_info[0]["app_id"] == "math", turn
                assert tool_info[0]["skill_id"] == "calculate", turn
                assert tool_info[0]["embed_id"] in wallet.embeds, turn
                assert wallet.embeds[tool_info[0]["embed_id"]]["status"] == "finished", turn
            else:
                assert tool_info == [], turn
            final = finalize_native_cache_state(
                native["state"], raw_final_output=native["raw_final_output"],
                content_markdown=visible, assistant_message_id=f"assistant-{turn}",
                tool_calls_info=tool_info,
            )
            assert final is not None, turn
            previous_state = await seal_native_embed_fingerprints(final, tool_info, wallet, request.user_id_hash)
            assert previous_state is not None, turn
            assert len(previous_state["embed_fingerprints"]) == (1 if turn < 3 else 2)
            history.append(_HistoryMessage(role="assistant", message_id=f"assistant-{turn}", content=visible))
        assert len(wallet.charges) == 7
        assert len([key for key in wallet.charges if key.startswith("ai-ask:")]) == 5
        assert len([key for key in wallet.charges if key.startswith("math-calculate:")]) == 2
        assert wallet.credits > 0
        assert len(native_calls) == 7
        assert all(call["native"] and call["matched"] for call in native_calls)
        assert [call["active_tools"] for call in native_calls] == [
            ["math-calculate"], ["math-calculate"], [], ["math-calculate"],
            ["math-calculate"], [], [],
        ]
        assert [call["baseline_tools"] for call in native_calls] == [["math-calculate"]] * 7
        assert [call["private_prior_outputs"] for call in native_calls] == [0, 1, 2, 3, 4, 5, 6]
        assert len({call["stable_prefix_sha256"] for call in native_calls}) == 1
        assert [call["paired_call_result_tail"] for call in native_calls] == [
            False, True, False, False, True, False, False,
        ]
        assert [call["cache_read"] for call in native_calls] == [0, 0, 80, 80, 80, 80, 80]
        assert [call["cache_write"] for call in native_calls] == [0] * 7
        assert all(row["credits"] > 0 for key, row in wallet.charges.items()
                   if key.startswith("ai-ask:"))
    finally:
        deactivate_mock_mode()


@pytest.mark.asyncio
async def test_five_turn_native_cache_processor_signed_fixture_and_seal(monkeypatch):
    await _run_offline(monkeypatch)


@pytest.mark.asyncio
async def test_missing_terminal_private_frame_cannot_be_sealed(monkeypatch):
    await _run_offline(monkeypatch, drop_frame_turn=2)
