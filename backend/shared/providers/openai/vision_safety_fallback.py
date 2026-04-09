# backend/shared/providers/openai/vision_safety_fallback.py
#
# GPT-5 mini vision safety fallback for the image safety pipeline.
#
# Invoked only when Gemini 3 Flash vision-safety returns an error (outage,
# quota, regional issue). Uses OpenAI's Chat Completions vision API with a
# tool_choice=forced function call — same schema as Gemini so the pipeline
# reasoner consumes identical structured output.
#
# Architecture: docs/architecture/image-safety-pipeline.md §4

import base64
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.google.vision_safety import (
    REPORT_FUNCTION_SCHEMA,
    SYSTEM_PROMPT,
    VisionSafetyFindings,
    _derive_flags,
)

logger = logging.getLogger(__name__)

OPENAI_SECRET_PATH = "kv/data/providers/openai"
GPT5_MINI_MODEL = "gpt-5-mini"


async def _get_openai_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    try:
        return await secrets_manager.get_secret(
            secret_path=OPENAI_SECRET_PATH, secret_key="api_key"
        )
    except Exception as e:
        logger.error(f"[VisionSafety/GPT5] Failed to load OpenAI key: {e}")
        return None


async def analyze_image_gpt5_mini(
    image_bytes: bytes,
    mime_type: str,
    *,
    secrets_manager: SecretsManager,
) -> VisionSafetyFindings:
    """
    Fallback VLM safety analysis via GPT-5 mini.

    Returns a VisionSafetyFindings object with the same shape as the Gemini
    primary so the rest of the pipeline is provider-agnostic.
    """
    findings = VisionSafetyFindings(provider="openai", model=GPT5_MINI_MODEL)

    api_key = await _get_openai_api_key(secrets_manager)
    if not api_key:
        findings.error = "no_api_key"
        findings.hard_block = True
        findings.hard_block_reason = "gpt5_mini_not_configured"
        return findings

    try:
        client = AsyncOpenAI(api_key=api_key)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{image_b64}"

        # OpenAI Chat Completions tool-forced call pattern
        tools = [
            {
                "type": "function",
                "function": {
                    "name": REPORT_FUNCTION_SCHEMA["name"],
                    "description": REPORT_FUNCTION_SCHEMA["description"],
                    "parameters": REPORT_FUNCTION_SCHEMA["parameters"],
                },
            }
        ]
        response = await client.chat.completions.create(
            model=GPT5_MINI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this image and call report_image_analysis.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
            tools=tools,  # type: ignore[arg-type]
            tool_choice={
                "type": "function",
                "function": {"name": REPORT_FUNCTION_SCHEMA["name"]},
            },
            # GPT-5 mini only supports the default temperature (1.0) — do not
            # override. Determinism is enforced by function-calling schema.
        )
    except Exception as e:
        logger.error(f"[VisionSafety/GPT5] API error: {e}", exc_info=True)
        findings.error = str(e)
        findings.hard_block = True
        findings.hard_block_reason = "gpt5_mini_api_error"
        return findings

    try:
        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise ValueError("no tool_calls in response")
        args = tool_calls[0].function.arguments or "{}"
        parsed = json.loads(args)
    except Exception as e:
        logger.error(
            f"[VisionSafety/GPT5] Failed to parse tool call: {e}", exc_info=True
        )
        findings.error = f"parse_error: {e}"
        findings.hard_block = True
        findings.hard_block_reason = "gpt5_mini_parse_error"
        return findings

    findings.raw = parsed
    findings.scene = str(parsed.get("scene", ""))[:500]
    findings.photorealistic = bool(parsed.get("photorealistic", False))
    findings.text_in_image = str(parsed.get("text_in_image", ""))[:2000]
    findings.detected_injection_attempt = bool(
        parsed.get("detected_injection_attempt", False)
    )
    findings.hard_block_recommended = bool(parsed.get("hard_block_recommended", False))
    findings.hard_block_reason = parsed.get("hard_block_reason") or None
    findings.concerning_elements = [
        str(e) for e in (parsed.get("concerning_elements") or [])
    ]
    findings.people = [
        dict(p) if isinstance(p, dict) else {} for p in (parsed.get("people") or [])
    ]

    _derive_flags(findings)
    logger.info(
        f"[VisionSafety/GPT5] block={findings.hard_block} "
        f"reason={findings.hard_block_reason} minor={findings.minor_present} "
        f"pf={findings.public_figure_detected}"
    )
    return findings
