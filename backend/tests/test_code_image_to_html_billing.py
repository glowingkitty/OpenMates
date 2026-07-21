# backend/tests/test_code_image_to_html_billing.py
#
# Billing contract tests for Code image-to-HTML. The feature charges actual
# Gemini token cost plus E2B render duration, while reserving a bounded maximum
# before provider calls.

from __future__ import annotations

from backend.apps.code.skills.image_to_html_skill import (
    ImageToHtmlUsage,
    calculate_image_to_html_credits,
)


def test_skill_response_usage_includes_actual_charge_metadata() -> None:
    from backend.apps.code.skills.image_to_html_skill import ImageToHtmlGenerationResult, _direct_result_payload

    payload = _direct_result_payload(
        ImageToHtmlGenerationResult(
            html="<!doctype html><html><body>Hello</body></html>",
            correction_passes_used=1,
            usage={"model": "gemini-3.1-pro-preview", "input_tokens": 1_000, "output_tokens": 500, "e2b_render_seconds": 61.0},
        ),
        max_correction_passes=2,
    )

    assert payload["usage"]["reserved_credits"] > payload["usage"]["credits_charged"]
    assert payload["usage"]["e2b_credits"] == 10
    assert payload["usage"]["credits_refunded"] >= 0


def test_actual_cost_credit_calculation_includes_tokens_e2b_and_minimum() -> None:
    usage = ImageToHtmlUsage(
        model="gemini-3.1-pro-preview",
        input_tokens=40_000,
        output_tokens=8_000,
        cache_read_tokens=20_000,
        e2b_render_seconds=38.2,
        correction_passes_used=2,
    )

    result = calculate_image_to_html_credits(
        usage,
        input_usd_per_million=2.0,
        output_usd_per_million=12.0,
        cache_read_usd_per_million=0.2,
        credits_per_usd=100,
        margin_multiplier=2.0,
        e2b_credits_per_started_minute=5,
        minimum_credits=30,
    )

    assert result.provider_cost_usd > 0
    assert result.e2b_credits == 5
    assert result.credits_charged >= 30
    assert result.usage.model == "gemini-3.1-pro-preview"


def test_credit_calculation_charges_each_started_e2b_minute() -> None:
    usage = ImageToHtmlUsage(model="gemini", e2b_render_seconds=61.0)

    result = calculate_image_to_html_credits(
        usage,
        credits_per_usd=100,
        e2b_credits_per_started_minute=5,
        minimum_credits=1,
    )

    assert result.e2b_credits == 10
    assert result.credits_charged >= 10

