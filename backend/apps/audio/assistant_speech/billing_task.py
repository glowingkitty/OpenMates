# backend/apps/audio/assistant_speech/billing_task.py
#
# Settles one sealed assistant response after all retryable segment work ends.
# The task reads integer counts and duration metadata only; speakable text never
# crosses this durable message-level billing boundary.

from __future__ import annotations

import asyncio
from typing import Any

from backend.apps.audio.assistant_speech.persistence import complete_manifest_billing, prepare_manifest_billing
from backend.apps.audio.pricing import ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL, calculate_assistant_response_speech_credits
from backend.apps.audio.tasks.common import charge_audio_generation_credits
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


@app.task(bind=True, name="apps.audio.tasks.assistant_speech_billing", base=BaseServiceTask, queue="app_music", autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def assistant_speech_billing_task(self: BaseServiceTask, arguments: dict[str, Any]) -> dict[str, object]:
    async def run() -> dict[str, object]:
        try:
            await self.initialize_core_services()
            billing = await prepare_manifest_billing(self._directus_service, str(arguments["manifest_id"]))
            if billing is None:
                return {"status": "pending"}
            submitted_characters = int(billing["submitted_characters"])
            model = str(billing["model"])
            if model != ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL:
                raise RuntimeError("Assistant speech manifest has an unsupported billing model")
            credits = calculate_assistant_response_speech_credits(submitted_characters=submitted_characters)
            if credits == 0:
                await complete_manifest_billing(self._directus_service, str(billing["manifest_row_id"]), usage_id=None)
                return {"status": "not_billable"}
            result = await charge_audio_generation_credits(
                user_id=str(billing["user_id"]), app_id="assistant_response_speech", skill_id="segment",
                task_id=f"assistant-speech:{arguments['manifest_id']}", request_id="aggregate", credits=credits,
                model_ref=f"elevenlabs/{model}", duration_seconds=float(billing["duration_seconds"]),
                chat_id=str(billing["chat_id"]), message_id=str(billing["assistant_message_id"]), external_request=False,
                api_key_hash=None, device_hash=None, api_key_name=None, log_prefix="[assistant-speech billing]", raise_on_failure=True,
            )
            usage_id = str((result or {}).get("usage_id") or "")
            if not usage_id:
                raise RuntimeError("Assistant speech billing did not return a usage identity")
            await complete_manifest_billing(self._directus_service, str(billing["manifest_row_id"]), usage_id=usage_id)
            return {"status": "committed", "usage_id": usage_id, "credits": credits}
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
