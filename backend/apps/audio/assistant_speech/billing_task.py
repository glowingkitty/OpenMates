# backend/apps/audio/assistant_speech/billing_task.py
#
# Settles each ready assistant speech segment promptly using a message-scoped
# cumulative character ledger. Speakable text never crosses billing.

from __future__ import annotations

import asyncio
from typing import Any

from backend.apps.audio.assistant_speech.persistence import complete_segment_billing, prepare_next_segment_billing
from backend.apps.audio.pricing import ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL, calculate_assistant_response_speech_credits
from backend.apps.audio.tasks.common import charge_audio_generation_credits
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


@app.task(bind=True, name="apps.audio.tasks.assistant_speech_billing", base=BaseServiceTask, queue="app_music", autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def assistant_speech_billing_task(self: BaseServiceTask, arguments: dict[str, Any]) -> dict[str, object]:
    async def run() -> dict[str, object]:
        try:
            await self.initialize_core_services()
            settled = 0
            charged = 0
            for _ in range(20):
                billing = await prepare_next_segment_billing(self._directus_service, str(arguments["manifest_id"]))
                if billing is None:
                    return {"status": "settled" if settled else "pending", "segments": settled, "credits": charged}
                model = str(billing["model"])
                if model != ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL:
                    raise RuntimeError("Assistant speech manifest has an unsupported billing model")
                before = calculate_assistant_response_speech_credits(submitted_characters=int(billing["settled_characters"]))
                after = calculate_assistant_response_speech_credits(
                    submitted_characters=int(billing["settled_characters"]) + int(billing["submitted_characters"])
                )
                credits = after - before
                usage_id = None
                if credits:
                    result = await charge_audio_generation_credits(
                        user_id=str(billing["user_id"]), app_id="assistant_response_speech", skill_id="segment",
                        task_id=f"assistant-speech:{arguments['manifest_id']}", request_id=str(billing["segment_id"]), credits=credits,
                        model_ref=f"elevenlabs/{model}", duration_seconds=float(billing["duration_seconds"]),
                        chat_id=str(billing["chat_id"]), message_id=str(billing["assistant_message_id"]), external_request=False,
                        api_key_hash=None, device_hash=None, api_key_name=None, log_prefix="[assistant-speech billing]", raise_on_failure=True,
                    )
                    usage_id = str((result or {}).get("usage_id") or "")
                    if not usage_id:
                        raise RuntimeError("Assistant speech billing did not return a usage identity")
                if await complete_segment_billing(self._directus_service, billing, usage_id=usage_id):
                    settled += 1
                    charged += credits
            raise RuntimeError("Assistant speech billing reached the per-run segment limit")
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


@app.task(bind=True, name="apps.audio.tasks.assistant_speech_billing_sweep", base=BaseServiceTask, queue="app_music")
def assistant_speech_billing_sweep_task(self: BaseServiceTask) -> dict[str, int]:
    """Repair ready assets whose worker died before or during settlement."""
    async def run() -> dict[str, int]:
        try:
            await self.initialize_core_services()
            rows = await self._directus_service.get_items(
                "assistant_speech_segments",
                params={"filter[status][_eq]": "ready", "filter[billing_usage_id][_null]": "true", "limit": 500},
                no_cache=True,
            )
            manifest_ids = {str(row["manifest_id"]) for row in rows if row.get("manifest_id")}
            for manifest_id in manifest_ids:
                app.send_task(
                    "apps.audio.tasks.assistant_speech_billing",
                    kwargs={"arguments": {"manifest_id": manifest_id}}, queue="app_music",
                )
            return {"manifests": len(manifest_ids)}
        finally:
            await self.cleanup_services()
    return asyncio.run(run())
