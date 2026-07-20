"""Python SDK user plan contract tests.

Purpose: verify the pip SDK exposes the encrypted /v1/user-plans contract as
CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or plan payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_plans.py
"""

from openmates import OpenMates


PLAN = {
    "plan_id": "plan-1",
    "encrypted_plan_key": "cipher-key",
    "encrypted_title": "cipher-title",
    "status": "draft",
    "created_at": 100,
    "updated_at": 100,
}


def test_pip_sdk_user_plan_methods_use_shared_plans_api(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/criteria"):
            return FakeResponse({"criteria": []})
        if url.endswith("/verification"):
            return FakeResponse({"verifications": []})
        if url.endswith("/assumptions"):
            return FakeResponse({"assumptions": []})
        if url.endswith("/reference-patterns"):
            return FakeResponse({"reference_patterns": []})
        return FakeResponse({"plans": [PLAN]})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if "/criteria" in url:
            return FakeResponse({"criterion": json})
        if "/assumptions" in url:
            return FakeResponse({"assumption": json})
        if "/reference-patterns" in url:
            return FakeResponse({"reference_pattern": json})
        if "/verification" in url:
            return FakeResponse({"verification": json})
        return FakeResponse({"plan": {**PLAN, **json}})

    def fake_patch(url, *, json, headers, timeout):
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        if "/assumptions/" in url:
            return FakeResponse({"assumption": json})
        return FakeResponse({"plan": {**PLAN, **json}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key="x")
    assert client.plans.list(status="draft", chat_id="chat-1")[0]["plan_id"] == "plan-1"
    assert client.plans.create(PLAN)["encrypted_title"] == "cipher-title"
    assert client.plans.update("plan-1", {"status": "active", "version": 1})["status"] == "active"
    assert client.plans.activate("plan-1", {"chat_id": "chat-1", "version": 2})["primary_chat_id"] == "chat-1"
    assert client.plans.complete("plan-1", {"version": 3})["plan_id"] == "plan-1"
    assert client.plans.create_criterion("plan-1", {"criterion_id": "AC-1", "encrypted_text": "cipher-ac", "created_at": 100})["criterion_id"] == "AC-1"
    assert client.plans.list_criteria("plan-1") == []
    assert client.plans.create_verification("plan-1", {"verification_id": "V-1", "kind": "manual_check", "created_at": 100})["verification_id"] == "V-1"
    assert client.plans.list_verifications("plan-1") == []
    assert client.plans.create_assumption("plan-1", {"assumption_id": "A-1", "encrypted_text": "cipher-assumption", "created_at": 100})["assumption_id"] == "A-1"
    assert client.plans.list_assumptions("plan-1") == []
    assert client.plans.update_assumption("plan-1", "A-1", {"status": "confirmed"})["status"] == "confirmed"
    assert client.plans.create_reference_pattern("plan-1", {"pattern_id": "RP-1", "encrypted_title": "cipher-pattern", "created_at": 100})["pattern_id"] == "RP-1"
    assert client.plans.list_reference_patterns("plan-1") == []
    assert client.plans.add_verification_evidence("plan-1", "V-1", {"status": "passed"})["status"] == "passed"

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans?status=draft&chat_id=chat-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans", "json": PLAN},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"status": "active", "version": 1}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/activate", "json": {"chat_id": "chat-1", "version": 2}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/complete", "json": {"version": 3}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/criteria", "json": {"criterion_id": "AC-1", "encrypted_text": "cipher-ac", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/criteria"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification", "json": {"verification_id": "V-1", "kind": "manual_check", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions", "json": {"assumption_id": "A-1", "encrypted_text": "cipher-assumption", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions"},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions/A-1", "json": {"status": "confirmed"}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/reference-patterns", "json": {"pattern_id": "RP-1", "encrypted_title": "cipher-pattern", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/reference-patterns"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification/V-1/evidence", "json": {"status": "passed"}},
    ]
