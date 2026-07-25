"""Python SDK user plan contract tests.

Purpose: verify the pip SDK exposes the encrypted /v1/user-plans contract as
CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or plan payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_plans.py
"""

from openmates import OpenMates
from openmates.sdk import _create_api_key_material, _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text


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
        if url.endswith("/runs/run-1"):
            return FakeResponse({"run": {"run_id": "run-1"}, "artifacts": []})
        if url.endswith("/learnings"):
            return FakeResponse({"learnings": []})
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
        if url.endswith("/learnings/create-tasks"):
            return FakeResponse({"tasks": [], "skipped": []})
        if "/learnings" in url:
            return FakeResponse({"learning": json})
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
        if "/learnings/" in url:
            return FakeResponse({"learning": json})
        if "/criteria/" in url:
            return FakeResponse({"criterion": json})
        if "/verification/" in url:
            return FakeResponse({"verification": json})
        if "/assumptions/" in url:
            return FakeResponse({"assumption": json})
        if "/reference-patterns/" in url:
            return FakeResponse({"reference_pattern": json})
        return FakeResponse({"plan": {**PLAN, **json}})

    def fake_delete(url, *, json, headers, timeout):
        requests_seen.append({"method": "DELETE", "url": url, "json": json})
        return FakeResponse({"deleted": True})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key="x")
    assert client.plans.list(status="draft", chat_id="chat-1")[0]["plan_id"] == "plan-1"
    assert client.plans.show("plan-1")["plan_id"] == "plan-1"
    assert client.plans.create(PLAN)["encrypted_title"] == "cipher-title"
    assert client.plans.update("plan-1", {"status": "active", "version": 1})["status"] == "active"
    attach_wrappers = [{"key_type": "master", "encrypted_plan_key": "cipher-key", "created_at": 100}]
    assert client.plans.attach("plan-1", {"chat_id": "chat-1", "version": 2, "key_wrappers": attach_wrappers})["primary_chat_id"] == "chat-1"
    assert client.plans.start("plan-1", {"version": 3})["status"] == "executing"
    assert client.plans.resume("plan-1", {"version": 4})["status"] == "active"
    assert client.plans.goal.set("plan-1", {"encrypted_goal": "cipher-goal"})["encrypted_goal"] == "cipher-goal"
    assert client.plans.current_focus.clear("plan-1")["encrypted_current_focus"] is None
    assert client.plans.open_questions.answer("plan-1", {"encrypted_open_questions": "cipher-answer"})["encrypted_open_questions"] == "cipher-answer"
    assert client.plans.complete("plan-1", {"version": 3})["plan_id"] == "plan-1"
    assert client.plans.success_criteria.add("plan-1", {"criterion_id": "AC-1", "encrypted_text": "cipher-ac", "created_at": 100})["criterion_id"] == "AC-1"
    assert client.plans.success_criteria.update("plan-1", "AC-1", {"status": "satisfied"})["status"] == "satisfied"
    assert client.plans.success_criteria.remove("plan-1", "AC-1") == {"deleted": True}
    assert client.plans.list_criteria("plan-1") == []
    assert client.plans.checks.add("plan-1", {"verification_id": "V-1", "kind": "manual_check", "created_at": 100})["verification_id"] == "V-1"
    assert client.plans.checks.update("plan-1", "V-1", {"status": "passed"})["status"] == "passed"
    assert client.plans.checks.get_run("plan-1", "V-1", "run-1")["run"]["run_id"] == "run-1"
    assert client.plans.checks.remove("plan-1", "V-1") == {"deleted": True}
    assert client.plans.list_verifications("plan-1") == []
    assert client.plans.assumptions.add("plan-1", {"assumption_id": "A-1", "encrypted_text": "cipher-assumption", "created_at": 100})["assumption_id"] == "A-1"
    assert client.plans.list_assumptions("plan-1") == []
    assert client.plans.assumptions.check("plan-1", "A-1")["status"] == "checking"
    assert client.plans.assumptions.waive("plan-1", "A-1", {"encrypted_waiver_reason": "cipher-reason"})["status"] == "waived"
    assert client.plans.assumptions.remove("plan-1", "A-1") == {"deleted": True}
    assert client.plans.reference_patterns.add("plan-1", {"pattern_id": "RP-1", "encrypted_title": "cipher-pattern", "created_at": 100})["pattern_id"] == "RP-1"
    assert client.plans.list_reference_patterns("plan-1") == []
    assert client.plans.reference_patterns.inspect("plan-1", "RP-1")["status"] == "inspected"
    assert client.plans.reference_patterns.remove("plan-1", "RP-1") == {"deleted": True}
    assert client.plans.learnings.create("plan-1", {"learning_id": "LRN-1", "type": "workflow_improvement", "target_kind": "workflow", "encrypted_title": "cipher-learning", "created_at": 100})["learning_id"] == "LRN-1"
    assert client.plans.learnings.list("plan-1") == []
    assert client.plans.learnings.update("plan-1", "LRN-1", {"status": "accepted"})["status"] == "accepted"
    assert client.plans.learnings.remove("plan-1", "LRN-1") == {"deleted": True}
    assert client.plans.learnings.create_tasks("plan-1", {"learning_ids": ["LRN-1"]}) == {"tasks": [], "skipped": []}
    assert client.plans.checks.add_evidence("plan-1", "V-1", {"status": "passed"})["status"] == "passed"

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans?status=draft&chat_id=chat-1"},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans?active_only=False"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans", "json": PLAN},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"status": "active", "version": 1}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/activate", "json": {"chat_id": "chat-1", "version": 2, "key_wrappers": attach_wrappers}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"version": 3, "status": "executing"}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"version": 4, "status": "active"}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"encrypted_goal": "cipher-goal"}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"encrypted_current_focus": None}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1", "json": {"encrypted_open_questions": "cipher-answer"}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/complete", "json": {"version": 3}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/criteria", "json": {"criterion_id": "AC-1", "encrypted_text": "cipher-ac", "created_at": 100}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/criteria/AC-1", "json": {"status": "satisfied"}},
        {"method": "DELETE", "url": "https://api.openmates.org/v1/user-plans/plan-1/criteria/AC-1", "json": None},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/criteria"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification", "json": {"verification_id": "V-1", "kind": "manual_check", "created_at": 100}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification/V-1", "json": {"status": "passed"}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification/V-1/runs/run-1"},
        {"method": "DELETE", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification/V-1", "json": None},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions", "json": {"assumption_id": "A-1", "encrypted_text": "cipher-assumption", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions"},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions/A-1", "json": {"status": "checking"}},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions/A-1", "json": {"encrypted_waiver_reason": "cipher-reason", "status": "waived"}},
        {"method": "DELETE", "url": "https://api.openmates.org/v1/user-plans/plan-1/assumptions/A-1", "json": None},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/reference-patterns", "json": {"pattern_id": "RP-1", "encrypted_title": "cipher-pattern", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/reference-patterns"},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/reference-patterns/RP-1", "json": {"status": "inspected"}},
        {"method": "DELETE", "url": "https://api.openmates.org/v1/user-plans/plan-1/reference-patterns/RP-1", "json": None},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/learnings", "json": {"learning_id": "LRN-1", "type": "workflow_improvement", "target_kind": "workflow", "encrypted_title": "cipher-learning", "created_at": 100}},
        {"method": "GET", "url": "https://api.openmates.org/v1/user-plans/plan-1/learnings"},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-plans/plan-1/learnings/LRN-1", "json": {"status": "accepted"}},
        {"method": "DELETE", "url": "https://api.openmates.org/v1/user-plans/plan-1/learnings/LRN-1", "json": None},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/learnings/create-tasks", "json": {"learning_ids": ["LRN-1"]}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-plans/plan-1/verification/V-1/evidence", "json": {"status": "passed"}},
    ]


def test_pip_sdk_plan_add_to_project_encrypts_linked_project_ids(monkeypatch):
    master_key = bytes([3]) * 32
    plan_key = bytes([4]) * 32
    project_key = bytes([5]) * 32
    api_key, material = _create_api_key_material("pip plan parity", master_key)
    plan = {
        "plan_id": "plan-1",
        "version": 1,
        "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, master_key),
        "encrypted_title": _encrypt_aes_gcm_text("Plan", plan_key),
        "encrypted_linked_project_ids": _encrypt_aes_gcm_text("[]", plan_key),
        "linked_project_ids": [],
        "status": "draft",
        "created_at": 100,
        "updated_at": 100,
    }
    seen_patch = {}

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        if url.endswith("/v1/user-plans?active_only=False"):
            return FakeResponse({"plans": [plan]})
        if url.endswith("/v1/projects?include_archived=true"):
            return FakeResponse({"projects": [{"project_id": "project-1", "encrypted_project_key": _encrypt_aes_gcm_bytes(project_key, master_key)}]})
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url, *, json, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        raise AssertionError(f"Unexpected POST {url}")

    def fake_patch(url, *, json, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert url.endswith("/v1/user-plans/plan-1")
        seen_patch.update(json)
        return FakeResponse({"plan": {**plan, **json}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key=api_key, device_id="test-device")
    updated = client.plans.add_to_project("plan-1", "project-1")
    assert updated["linked_project_ids"] == ["project-1"]
    assert isinstance(seen_patch["encrypted_linked_project_ids"], str)
    assert seen_patch["linked_project_ids"] == ["project-1"]
    assert [wrapper["key_type"] for wrapper in seen_patch["key_wrappers"]] == ["master", "project"]
