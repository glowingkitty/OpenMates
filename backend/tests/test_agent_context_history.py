"""Client receipt details must not become queued inference or debug history."""
import json

from pydantic import BaseModel

from backend.shared.python_utils.agent_context_history import project_agent_context_history


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom,chats.persistence.client-encrypted
def test_receipt_replay_strips_bodies_and_preserves_dedup_without_mutating_client_transcript():
    secret = "PRIVATE-GUIDE-AND-CORRECTION-SENTINEL"
    history = [{"role": "system", "content": json.dumps({"type": "rules_loaded", "set_key": "a" * 64,
        "rules": [{"id": "project-rule:guide", "title": secret, "revision": "b" * 64, "body": secret}], "extra": secret})},
        {"role": "system", "content": json.dumps({"type": "chat_direction_correction", "delivery_id": "delivery-1", "instruction": secret})}]
    clean = project_agent_context_history(history)
    assert secret not in json.dumps(clean)
    assert secret in json.dumps(history)
    assert json.loads(clean[0]["content"])["set_key"] == "a" * 64
    assert json.loads(clean[0]["content"])["rules"] == [{"id": "project-rule:guide", "revision": "b" * 64}]
    assert json.loads(clean[1]["content"])["delivery_id"] == "delivery-1"
    assert project_agent_context_history(clean) == clean


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom,chats.persistence.client-encrypted
def test_malformed_and_oversized_receipts_fail_closed_but_actual_messages_survive():
    secret = "PRIVATE-REPLAY-SENTINEL"
    ordinary = [{"role": "user", "content": '{"type":"rules_loaded","body":"' + secret + '"}'},
                {"role": "assistant", "content": secret}, {"role": "system", "content": "Existing protocol"}]
    receipts = [{"role": "system", "content": '{"type":"rules_loaded","body":"' + secret},
                {"role": "system", "content": '{"type":"rules_loaded","body":"' + secret * 8000 + '"}'}]
    assert project_agent_context_history(ordinary) == ordinary
    assert secret not in json.dumps(project_agent_context_history(receipts))


# contract-test: supporting surface=rest_api assertions=rules.transparency.applied-set,chats.persistence.client-encrypted
def test_pydantic_history_keeps_message_identity_and_drops_private_details():
    class Message(BaseModel):
        role: str
        content: str
        id: str
    original = Message(role="system", id="receipt-1", content=json.dumps({
        "type": "project_authoring_recommendation", "recommendation_id": "recommendation-1", "title": "PRIVATE-TITLE"}))
    cleaned = project_agent_context_history([original])[0]
    assert isinstance(cleaned, Message) and cleaned.id == original.id
    assert "PRIVATE-TITLE" not in cleaned.model_dump_json()
    assert "PRIVATE-TITLE" in original.content
    unrelated = [{"role": "system", "content": '{"type":[]}'}]
    assert project_agent_context_history(unrelated) == unrelated
