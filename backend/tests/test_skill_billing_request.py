"""Media jobs must send stable charge identities to either credit ledger."""

import pytest

from backend.shared.python_utils.team_skill_billing import skill_billing_request


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("app_id,skill_id", [
    ("videos", "generate"), ("videos", "create"), ("images", "generate"),
    ("images", "vectorize"), ("music", "generate"), ("models3d", "generate"),
    ("code", "image_to_html"),
])
def test_personal_media_outputs_have_stable_distinct_identities(app_id, skill_id):
    original = {"user_id": "user-1", "user_id_hash": "hash-1", "credits": 7,
                "app_id": app_id, "skill_id": skill_id, "usage_details": {"units_processed": 1}}
    path, payload = skill_billing_request(original, None, event_id="output-1")
    assert path == "/internal/billing/charge"
    assert payload == {**original, "idempotency_key": "app-skill:output-1"}
    assert "idempotency_key" not in original
    assert skill_billing_request(original, None, event_id="output-1") == (path, payload)
    _, second = skill_billing_request(original, None, event_id="output-2")
    assert second["idempotency_key"] != payload["idempotency_key"]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,assistant-speech.billing.segment-success-once
@pytest.mark.parametrize("key", ["audio:task-1:1", "audio:task-1:child:0", "audio:assistant-speech:manifest-1:segment-0"])
def test_existing_personal_speech_identity_is_preserved(key):
    payload = {"user_id": "user-1", "idempotency_key": key}
    assert skill_billing_request(payload, None, event_id="other-event") == ("/internal/billing/charge", payload)


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("team_id", [None, "team-1"])
def test_long_event_identity_is_stable_and_fits_billing_schema(team_id):
    payload = {"user_id": "user-1", "credits": 1, "app_id": "videos", "skill_id": "generate"}
    event_id = "output-" + "x" * 300
    first = skill_billing_request(payload, team_id, event_id=event_id)
    assert len(first[1]["idempotency_key"]) <= 255
    assert skill_billing_request(payload, team_id, event_id=event_id) == first
    assert skill_billing_request(payload, team_id, event_id=event_id + "y")[1]["idempotency_key"] != first[1]["idempotency_key"]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("team_id", [None, "team-1"])
def test_missing_event_identity_is_rejected(team_id):
    with pytest.raises(ValueError, match="requires an event ID"):
        skill_billing_request({"user_id": "user-1"}, team_id, event_id="")
