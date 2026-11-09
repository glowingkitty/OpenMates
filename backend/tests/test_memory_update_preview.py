# contract-test-file: supporting
# Memory update preview parsing and preview billing (moved from the retired context suggestion tests).
# Run: python3 -m pytest backend/tests/test_memory_update_preview.py -v
import asyncio

import pytest

from backend.apps.ai.processing import memory_update_preview as preview

UPDATED = "---\ntitle: Coffee order\nwhen_to_use: Ordering coffee\nload_mode: ask_first\n---\n\nOat latte.\n"


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_preview_unchanged_and_updated_paths():
    assert preview.interpret_update({"unchanged": True}, UPDATED) is None
    assert preview.interpret_update({"unchanged": False, "document": UPDATED}, UPDATED) is None
    assert preview.interpret_update({"document": UPDATED.replace("Oat", "Soy")}, UPDATED).startswith("---")
    with pytest.raises(preview.MemoryPreviewError):
        preview.interpret_update({"document": "no frontmatter"}, UPDATED)


class FakeBilling:
    def __init__(self):
        self.calls = []

    async def charge_user_credits(self, **kw):
        self.calls.append(kw)


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.billing
def test_preview_charged_to_chat_without_private_text(monkeypatch):
    from backend.apps.ai.processing import memory_preview_billing as route
    monkeypatch.setattr(route, "build_model_usage_breakdown", lambda buckets, lookup: {
        "credits_charged": 3, "input_tokens": 100, "output_tokens": 20, "entries": []})
    secret_memory, secret_chat = "PRIVATE-MEMORY-BODY", "PRIVATE-CHAT-TEXT"
    buckets = route.priced_buckets({"model_id": "google/gemini-3.5-flash-lite", "input_tokens": 100, "output_tokens": 20})
    billing = FakeBilling()
    credits = asyncio.run(route.charge_preview(billing, None, user_id="u", user_id_hash="h", chat_id="chat-1",
                                               operation_id="op", buckets=buckets))
    call = billing.calls[0]
    assert credits == 3 and call["credits_to_deduct"] == 3 and call["usage_details"]["chat_id"] == "chat-1"
    assert call["usage_details"]["purpose"] == "memory_update_preview"
    assert secret_memory not in repr(call) and secret_chat not in repr(call)
    assert set(call["usage_details"]) == {"chat_id", "model_used", "input_tokens", "output_tokens", "purpose", "llm_usage_breakdown"}
