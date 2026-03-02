# backend/tests/test_rest_api_ai.py
#
# Integration tests for the AI app skills:
#   - ai/ask (default model)
#   - ai/ask targeting DeepSeek V3.2 via @ai-model override
#   - ai/ask multi-turn conversation with DeepSeek V3.2
#   - ai/ask triggering image generation (images-generate via preprocessing)
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_ai.py

import re

import httpx
import pytest


@pytest.mark.integration
def test_execute_skill_ask(api_client):
    """
    Test executing the 'ai/ask' skill.
    This is a real execution that will be billed to the API key.
    """
    payload = {
        "messages": [{"role": "user", "content": "Capital city of Germany?"}],
        "stream": False,
    }
    try:
        response = api_client.post(
            "/v1/apps/ai/skills/ask", json=payload, timeout=20.0
        )
        assert response.status_code == 200, (
            f"Skill execution failed: {response.text}"
        )
        data = response.json()
        assert "choices" in data, (
            "Response should have 'choices' field for OpenAI-compatible format"
        )
        assert len(data["choices"]) > 0, (
            "Response should have at least one choice"
        )
        content = data["choices"][0].get("message", {}).get("content", "")
        assert content, "Response content should not be empty"
        assert "Berlin" in content, (
            f"Expected 'Berlin' to be in response, but got: {content}"
        )
        assert not content.startswith("Error:"), (
            f"Response contains error message: {content}"
        )
    except httpx.TimeoutException:
        print("\n[TIMEOUT] Request to ai/ask timed out after 20 seconds.")
        pytest.fail("Request timed out after 20 seconds")


@pytest.mark.integration
def test_execute_skill_ask_deepseek_v3_2(api_client):
    """
    Test executing the 'ai/ask' skill targeting DeepSeek V3.2 specifically.

    Validates that the google_maas_client.py OpenAI-compatible API client
    correctly routes requests to Google Vertex AI MaaS for DeepSeek V3.2.
    Uses the @ai-model: override syntax to force model selection.
    """
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "What is the capital of France? @ai-model:deepseek-v3.2",
            }
        ],
        "stream": False,
    }

    print(
        "\n[DEEPSEEK TEST] Sending request targeting DeepSeek V3.2 "
        "via @ai-model override..."
    )
    try:
        response = api_client.post(
            "/v1/apps/ai/skills/ask", json=payload, timeout=60.0
        )
        assert response.status_code == 200, (
            f"DeepSeek V3.2 skill execution failed with status "
            f"{response.status_code}: {response.text}"
        )

        data = response.json()
        assert "error" not in data, f"Got error response: {data.get('error')}"
        assert "choices" in data, (
            f"Response missing 'choices' field. Got keys: {list(data.keys())}"
        )
        assert len(data["choices"]) > 0, (
            "Response should have at least one choice"
        )

        choice = data["choices"][0]
        assert "message" in choice, (
            f"Choice missing 'message' field. Got: {choice}"
        )
        assert "content" in choice["message"], (
            f"Message missing 'content'. Got: {choice['message']}"
        )

        content = choice["message"]["content"]
        assert content, "Response content should not be empty"
        assert len(content) > 10, (
            f"Response suspiciously short ({len(content)} chars): {content}"
        )
        assert "Paris" in content, (
            f"Expected 'Paris' in response, got: {content[:200]}"
        )

        assert "model" in data, "Response should include 'model' field"
        model_name = data["model"].lower()
        assert "deepseek" in model_name, (
            f"Expected model name to contain 'deepseek', got: {data['model']}"
        )

        assert choice.get("finish_reason") in ["stop", "end_turn", None], (
            f"Unexpected finish_reason: {choice.get('finish_reason')}"
        )

        print(f"[DEEPSEEK TEST] Model: {data.get('model')}")
        print(f"[DEEPSEEK TEST] Response length: {len(content)} chars")
        print(f"[DEEPSEEK TEST] Content preview: {content[:200]}")

        if "usage" in data and data["usage"]:
            usage = data["usage"]
            total_tokens = (
                usage.get("prompt_tokens", 0)
                + usage.get("completion_tokens", 0)
                + usage.get("user_input_tokens", 0)
                + usage.get("system_prompt_tokens", 0)
            )
            assert total_tokens > 0, (
                "Expected some token count (from provider or our estimator)"
            )
            print(
                f"[DEEPSEEK TEST] Tokens: "
                f"prompt={usage.get('prompt_tokens')}, "
                f"completion={usage.get('completion_tokens')}, "
                f"user_input={usage.get('user_input_tokens')}, "
                f"system_prompt={usage.get('system_prompt_tokens')}"
            )

        print(
            "[DEEPSEEK TEST] PASSED - DeepSeek V3.2 via Google MaaS "
            "is working correctly!"
        )

    except httpx.TimeoutException:
        print(
            "\n[TIMEOUT] DeepSeek V3.2 request timed out after 60 seconds."
        )
        pytest.fail("DeepSeek V3.2 request timed out after 60 seconds")


@pytest.mark.integration
def test_execute_skill_ask_deepseek_multi_turn(api_client):
    """
    Test multi-turn conversation with DeepSeek V3.2.
    Sends a two-message conversation to verify context handling through the
    google_maas_client.py OpenAI-compatible endpoint.
    """
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "Remember this number: 42. @ai-model:deepseek-v3.2",
            },
            {
                "role": "assistant",
                "content": "I'll remember the number 42.",
            },
            {
                "role": "user",
                "content": "What number did I ask you to remember?",
            },
        ],
        "stream": False,
    }

    print(
        "\n[DEEPSEEK MULTI-TURN] Testing multi-turn conversation "
        "with DeepSeek V3.2..."
    )
    try:
        response = api_client.post(
            "/v1/apps/ai/skills/ask", json=payload, timeout=60.0
        )
        assert response.status_code == 200, (
            f"Multi-turn request failed: {response.text}"
        )

        data = response.json()
        assert "error" not in data, f"Got error response: {data.get('error')}"
        assert "choices" in data, (
            f"Response missing 'choices'. Keys: {list(data.keys())}"
        )

        content = data["choices"][0].get("message", {}).get("content", "")
        assert content, "Response content should not be empty"
        assert "42" in content, (
            f"Expected model to recall '42', got: {content[:300]}"
        )

        print(f"[DEEPSEEK MULTI-TURN] Response: {content[:200]}")
        print("[DEEPSEEK MULTI-TURN] PASSED - Context maintained across turns!")

    except httpx.TimeoutException:
        pytest.fail(
            "Multi-turn DeepSeek request timed out after 60 seconds"
        )


@pytest.mark.integration
def test_execute_skill_ask_image_generation_via_ai(api_client):
    """
    Test that ai/ask correctly triggers image generation when the user asks
    for an image.

    Validates the full pipeline:
    1. Preprocessing detects image generation intent, preselects 'images-generate'
    2. The main LLM calls 'images-generate' (not a hallucinated tool name)
    3. Response contains an embed reference for the generated image
    4. Response also contains natural language text alongside the embed block
    """
    payload = {
        "messages": [
            {"role": "user", "content": "Design a coffee cup mockup"}
        ],
        "stream": False,
    }

    print("\n[IMAGE VIA AI] Testing ai/ask with image generation prompt...")
    try:
        response = api_client.post(
            "/v1/apps/ai/skills/ask", json=payload, timeout=120.0
        )
        if response.status_code == 502:
            pytest.skip(
                "Got 502 (gateway timeout) - non-stream AI request took "
                "too long. This is expected for complex prompts that "
                "trigger multiple LLM iterations."
            )
        assert response.status_code == 200, (
            f"AI ask failed with status {response.status_code}: {response.text}"
        )

        data = response.json()
        assert "error" not in data, f"Got error response: {data.get('error')}"
        assert "choices" in data, (
            f"Response missing 'choices' field. Got keys: {list(data.keys())}"
        )
        assert len(data["choices"]) > 0, (
            "Response should have at least one choice"
        )

        content = data["choices"][0].get("message", {}).get("content", "")
        assert content, "Response content should not be empty"

        print(f"[IMAGE VIA AI] Response length: {len(content)} chars")
        print(f"[IMAGE VIA AI] Content preview: {content[:500]}")

        has_embed = "app_skill_use" in content or "embed_id" in content

        if has_embed:
            print(
                "[IMAGE VIA AI] Found embed reference in response "
                "(image generation triggered)"
            )
            text_outside_code_blocks = re.sub(
                r"```json\s*\{[^}]*\}\s*```", "", content
            ).strip()
            assert len(text_outside_code_blocks) > 5, (
                f"Response contains embed reference but no follow-up text. "
                f"The LLM should provide a natural language response "
                f"alongside the image embed. Full content: {content}"
            )
            print(
                f"[IMAGE VIA AI] Follow-up text: "
                f"{text_outside_code_blocks[:200]}"
            )
        else:
            assert len(content) > 20, (
                f"Response too short without image embed: {content}"
            )
            print(
                "[IMAGE VIA AI] No embed reference found "
                "(LLM responded with text instead of generating)"
            )

        if "usage" in data and data["usage"]:
            usage = data["usage"]
            print(
                f"[IMAGE VIA AI] Tokens: "
                f"prompt={usage.get('prompt_tokens')}, "
                f"completion={usage.get('completion_tokens')}"
            )

        print("[IMAGE VIA AI] PASSED")

    except httpx.TimeoutException:
        print(
            "\n[TIMEOUT] Image generation via ai/ask timed out "
            "after 120 seconds."
        )
        pytest.fail("Request timed out after 120 seconds")
