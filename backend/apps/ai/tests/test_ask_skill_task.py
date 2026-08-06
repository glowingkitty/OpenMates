"""
Regression tests for AI ask task chat-history boundaries.

Compression summaries are server-readable context for model processing. They
must stay out of Directus chat history unless a client supplies client-encrypted
ciphertext for that history entry.
"""

from pathlib import Path


def test_chat_compression_does_not_persist_server_encrypted_summary_to_history():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    compression_block = source.split("Compression succeeded:", maxsplit=1)[1]
    compression_block = compression_block.split(
        "# Update request_data.message_history with compressed version",
        maxsplit=1,
    )[0]

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
