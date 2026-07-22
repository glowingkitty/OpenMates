# backend/tests/test_image_to_html_generator.py
#
# Unit tests for the provider-level Code image-to-HTML orchestration. The real
# implementation uses Gemini and E2B, but these tests inject deterministic fakes
# to prove validation repair, visual correction pass accounting, and the
# no-local-rendering boundary without making provider calls.

from __future__ import annotations

import sys
import types

from backend.shared.providers.e2b_html_renderer import E2BHtmlRenderResult
from backend.shared.providers.image_to_html_generator import (
    ExtractedImageAsset,
    GeneratedHtmlCandidate,
    HtmlGenerationUsage,
    ImageToHtmlGenerator,
    SourceImageDimensions,
    _generate_html_with_gemini,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"


async def fake_empty_asset_extractor(**_kwargs):
    return [], HtmlGenerationUsage(model="fake")


async def test_generator_repairs_invalid_external_reference_before_render() -> None:
    prompts: list[str] = []
    rendered_html: list[str] = []

    async def fake_gemini(**kwargs):
        prompts.append(kwargs["prompt"])
        if len(prompts) == 1:
            return GeneratedHtmlCandidate(
                html='<html><head><link href="https://fonts.example/css" rel="stylesheet"></head><body>Hello</body></html>',
                usage=HtmlGenerationUsage(model="fake", input_tokens=10, output_tokens=20),
            )
        return GeneratedHtmlCandidate(
            html="<!doctype html><html><head><style>body{font-family:sans-serif}</style></head><body>Hello</body></html>",
            usage=HtmlGenerationUsage(model="fake", input_tokens=5, output_tokens=10),
        )

    def fake_renderer(**kwargs):
        rendered_html.append(kwargs["html"])
        return E2BHtmlRenderResult(sandbox_id="sandbox-1", screenshot_bytes=PNG_BYTES, duration_seconds=2.5)

    generator = ImageToHtmlGenerator(
        gemini_html_generator=fake_gemini,
        asset_extractor=fake_empty_asset_extractor,
        renderer=fake_renderer,
        e2b_api_key="test-e2b-key",
    )

    result = await generator.generate(
        image_bytes=PNG_BYTES,
        mime_type="image/png",
        max_correction_passes=0,
    )

    assert result.html.startswith("<!doctype html>")
    assert rendered_html == [result.html]
    assert result.usage["input_tokens"] == 15
    assert result.usage["output_tokens"] == 30
    assert result.usage["validation_repair_attempts"] == 1
    assert result.validation_warnings
    assert "https://fonts.example" not in result.validation_warnings[0]


async def test_generator_uses_e2b_render_screenshot_for_correction_pass() -> None:
    calls: list[dict[str, object]] = []
    render_calls: list[dict[str, object]] = []

    async def fake_gemini(**kwargs):
        calls.append(kwargs)
        body = "First" if len(calls) == 1 else "Improved"
        return GeneratedHtmlCandidate(
            html=f"<!doctype html><html><body>{body}</body></html>",
            usage=HtmlGenerationUsage(model="fake", input_tokens=1, output_tokens=2),
        )

    def fake_renderer(**kwargs):
        render_calls.append(kwargs)
        return E2BHtmlRenderResult(sandbox_id="sandbox-1", screenshot_bytes=PNG_BYTES, duration_seconds=1.0)

    generator = ImageToHtmlGenerator(
        gemini_html_generator=fake_gemini,
        asset_extractor=fake_empty_asset_extractor,
        renderer=fake_renderer,
        e2b_api_key="test-e2b-key",
    )

    result = await generator.generate(
        image_bytes=PNG_BYTES,
        mime_type="image/png",
        max_correction_passes=1,
    )

    assert result.html == "<!doctype html><html><body>Improved</body></html>"
    assert result.correction_passes_used == 1
    assert result.usage["e2b_render_seconds"] == 2.0
    assert result.usage["extracted_asset_count"] == 0
    assert calls[1]["current_html"] == "<!doctype html><html><body>First</body></html>"
    assert calls[1]["rendered_screenshot_bytes"] == PNG_BYTES
    assert calls[1]["source_dimensions"] == SourceImageDimensions(width=1, height=1)
    assert render_calls == [
        {
            "html": "<!doctype html><html><body>First</body></html>",
            "api_key": "test-e2b-key",
            "viewport_width": 1,
            "viewport_height": 1,
        },
        {
            "html": "<!doctype html><html><body>Improved</body></html>",
            "api_key": "test-e2b-key",
            "viewport_width": 1,
            "viewport_height": 1,
        },
    ]


async def test_generator_inlines_extracted_asset_placeholders() -> None:
    asset_data_url = "data:image/png;base64,QUJD"
    calls: list[dict[str, object]] = []
    rendered_html: list[str] = []

    async def fake_asset_extractor(**_kwargs):
        return [
            ExtractedImageAsset(
                placeholder="__OPENMATES_EXTRACTED_ASSET_1__",
                label="logo",
                description="small logo mark",
                data_url=asset_data_url,
                box_2d=[10, 20, 30, 40],
                pixel_box=(1, 2, 3, 4),
                width=2,
                height=2,
            )
        ], HtmlGenerationUsage(model="fake", input_tokens=3, output_tokens=4)

    async def fake_gemini(**kwargs):
        calls.append(kwargs)
        return GeneratedHtmlCandidate(
            html='<!doctype html><html><body><img src="__OPENMATES_EXTRACTED_ASSET_1__" alt=""></body></html>',
            usage=HtmlGenerationUsage(model="fake", input_tokens=1, output_tokens=2),
        )

    def fake_renderer(**kwargs):
        rendered_html.append(kwargs["html"])
        return E2BHtmlRenderResult(sandbox_id="sandbox-1", screenshot_bytes=PNG_BYTES, duration_seconds=1.0)

    generator = ImageToHtmlGenerator(
        gemini_html_generator=fake_gemini,
        asset_extractor=fake_asset_extractor,
        renderer=fake_renderer,
        e2b_api_key="test-e2b-key",
    )

    result = await generator.generate(
        image_bytes=PNG_BYTES,
        mime_type="image/png",
        max_correction_passes=0,
    )

    assert result.html == f'<!doctype html><html><body><img src="{asset_data_url}" alt=""></body></html>'
    assert rendered_html == [result.html]
    assert result.usage["extracted_asset_count"] == 1
    assert result.usage["input_tokens"] == 4
    assert result.usage["output_tokens"] == 6
    assert "__OPENMATES_EXTRACTED_ASSET_1__" in calls[0]["prompt"]


async def test_default_gemini_path_reuses_existing_google_ai_studio_wrapper(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_invoke_google_ai_studio_chat_completions(**kwargs):
        captured.update(kwargs)
        usage = types.SimpleNamespace(prompt_token_count=11, candidates_token_count=7, cached_content_token_count=3)
        return types.SimpleNamespace(
            success=True,
            direct_message_content="<!doctype html><html><body>Wrapped</body></html>",
            error_message=None,
            usage=usage,
        )

    fake_google_client = types.ModuleType("backend.apps.ai.llm_providers.google_client")
    fake_google_client.invoke_google_ai_studio_chat_completions = fake_invoke_google_ai_studio_chat_completions
    monkeypatch.setitem(sys.modules, "backend.apps.ai.llm_providers.google_client", fake_google_client)

    result = await _generate_html_with_gemini(
        model_id="gemini-3.6-flash",
        secrets_manager=object(),
        prompt="Create HTML",
        image_bytes=PNG_BYTES,
        mime_type="image/png",
        current_html="<html></html>",
        rendered_screenshot_bytes=PNG_BYTES,
    )

    assert result.html.startswith("<!doctype html>")
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert captured["model_id"] == "gemini-3.6-flash"
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 50000
    assert captured["stream"] is False
    messages = captured["messages"]
    assert isinstance(messages, list)
    user_content = messages[1]["content"]
    assert user_content[0]["type"] == "text"
    assert "Original screenshot" in user_content[0]["text"]
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user_content[1]["image_url"]["detail"] == "high"
    assert user_content[-1] == {"type": "text", "text": "Create HTML"}
