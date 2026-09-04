"""Python SDK user plan contract tests.

Purpose: verify the pip SDK exposes the encrypted /v1/user-plans contract as
CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or plan payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_plans.py
"""

# contract-test-file: tooling

from openmates import OpenMates
from openmates.sdk import _create_api_key_material, _encrypted_object_slug_metadata, _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text


PLAN = {
    "plan_id": "plan-1",
    "encrypted_title": "cipher-title",
    "status": "draft",
    "created_at": 100,
    "updated_at": 100,
}


def assert_no_plaintext_marker(value, marker):
    assert marker not in str(value)


# contract-test: direct surface=sdks.pip assertions=plans.content.client-encrypted,plans.lifecycle.visible,plans.key-wrappers.contextual,plans.execution.gates-evidence,plans.surface.semantic-parity
def test_pip_sdk_user_plan_methods_use_shared_plans_api(monkeypatch):
    requests_seen = []
    master_key = bytes([8]) * 32
    plan_key = bytes([9]) * 32
    chat_key = bytes([10]) * 32
    api_key, material = _create_api_key_material("pip plan cleartext", master_key)
    encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, master_key)
    plan = {
        **PLAN,
        "key_wrappers": [{"key_type": "master", "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, master_key)}],
        "encrypted_title": _encrypt_aes_gcm_text("Plan", plan_key),
        "encrypted_goal": _encrypt_aes_gcm_text("Goal", plan_key),
        "encrypted_open_questions": _encrypt_aes_gcm_text("Question", plan_key),
        "encrypted_linked_project_ids": _encrypt_aes_gcm_text("[]", plan_key),
        "version": 1,
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        assert headers["Authorization"] == f"Bearer {api_key}"
        if url.endswith("/v1/sdk/chats/chat-1"):
            return FakeResponse({"chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": _encrypt_aes_gcm_text("Chat", chat_key)}})
        if url.endswith("/v1/sdk/chats?limit=0&offset=0"):
            return FakeResponse({"chats": [{"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": _encrypt_aes_gcm_text("Chat", chat_key)}]})
        if url.endswith("/v1/user-plans/plan-1"):
            return FakeResponse({"plan": plan})
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
        return FakeResponse({"plans": [plan]})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
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
        return FakeResponse({"plan": {**plan, **json}})

    def fake_patch(url, *, json, headers, timeout):
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
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
        return FakeResponse({"plan": {**plan, **json}})

    def fake_delete(url, *, json, headers, timeout):
        requests_seen.append({"method": "DELETE", "url": url, "json": json})
        return FakeResponse({"deleted": True})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key=api_key, device_id="test-device")
    assert client.plans.list(status="draft", chat_id="chat-1")[0]["plan_id"] == "plan-1"
    assert client.plans.show("plan-1")["plan_id"] == "plan-1"
    assert client.plans.create({"title": "Created plan", "goal": "Deliver the plan"})["title"] == "Created plan"
    assert client.plans.update("plan-1", {"status": "active"})["status"] == "active"
    assert client.plans.attach("plan-1", chat_id="chat-1")["primary_chat_id"] == "chat-1"
    assert client.plans.start("plan-1")["status"] == "executing"
    assert client.plans.resume("plan-1")["status"] == "active"
    assert client.plans.goal.set("plan-1", "Updated goal")["goal"] == "Updated goal"
    user_flows = [{"flow_id": "FLOW-1", "title": "Publish", "steps": [{"step_id": "STEP-1", "text": "Review"}], "expected_outcome": "Published"}]
    assert client.plans.user_flows.set("plan-1", user_flows)["user_flows"] == user_flows
    assert client.plans.user_flows.clear("plan-1")["user_flows"] == []
    assert client.plans.open_questions.answer("plan-1", "Answered")["open_questions"] == "Answered"
    assert client.plans.complete("plan-1")["plan_id"] == "plan-1"
    criterion = client.plans.success_criteria.add("plan-1", {"criterion_id": "AC-1", "text": "Plain AC"})
    assert criterion["criterion_id"] == "AC-1"
    assert criterion["text"] == "Plain AC"
    assert client.plans.success_criteria.update("plan-1", "AC-1", {"status": "satisfied"})["status"] == "satisfied"
    assert client.plans.success_criteria.remove("plan-1", "AC-1") == {"deleted": True}
    assert client.plans.list_criteria("plan-1") == []
    check = client.plans.checks.add("plan-1", {"verification_id": "V-1", "kind": "manual_check", "command": "pytest"})
    assert check["verification_id"] == "V-1"
    assert check["command"] == "pytest"
    assert client.plans.checks.update("plan-1", "V-1", {"status": "passed"})["status"] == "passed"
    assert client.plans.checks.get_run("plan-1", "V-1", "run-1")["run"]["run_id"] == "run-1"
    assert client.plans.checks.remove("plan-1", "V-1") == {"deleted": True}
    assert client.plans.list_verifications("plan-1") == []
    assumption = client.plans.assumptions.add("plan-1", {"assumption_id": "A-1", "text": "Plain assumption"})
    assert assumption["assumption_id"] == "A-1"
    assert assumption["text"] == "Plain assumption"
    assert client.plans.list_assumptions("plan-1") == []
    assert client.plans.assumptions.check("plan-1", "A-1")["status"] == "checking"
    assert client.plans.assumptions.waive("plan-1", "A-1", {"waiver_reason": "Known limitation"})["status"] == "waived"
    assert client.plans.assumptions.remove("plan-1", "A-1") == {"deleted": True}
    pattern = client.plans.reference_patterns.add("plan-1", {"pattern_id": "RP-1", "title": "Plain pattern"})
    assert pattern["pattern_id"] == "RP-1"
    assert pattern["title"] == "Plain pattern"
    assert client.plans.list_reference_patterns("plan-1") == []
    assert client.plans.reference_patterns.inspect("plan-1", "RP-1")["status"] == "inspected"
    assert client.plans.reference_patterns.remove("plan-1", "RP-1") == {"deleted": True}
    learning = client.plans.learnings.create("plan-1", {"learning_id": "LRN-1", "type": "workflow_improvement", "target_kind": "workflow", "title": "Plain learning"})
    assert learning["learning_id"] == "LRN-1"
    assert learning["title"] == "Plain learning"
    assert client.plans.learnings.list("plan-1") == []
    assert client.plans.learnings.update("plan-1", "LRN-1", {"status": "accepted"})["status"] == "accepted"
    assert client.plans.learnings.remove("plan-1", "LRN-1") == {"deleted": True}
    assert client.plans.learnings.create_tasks("plan-1", {"learning_ids": ["LRN-1"]}) == {"tasks": [], "skipped": []}
    assert client.plans.checks.add_evidence("plan-1", "V-1", {"status": "passed", "result_summary": "Passed locally"})["status"] == "passed"

    for marker in ["Plain AC", "Plain assumption", "Plain pattern", "Plain learning", "Passed locally", "Published"]:
        assert_no_plaintext_marker(requests_seen, marker)

    urls = [request["url"].replace("https://api.openmates.org", "") for request in requests_seen]
    assert "/v1/sdk/session" in urls
    assert "/v1/user-plans" in urls
    assert any(url.startswith("/v1/user-plans?status=draft") for url in urls)
    assert "/v1/user-plans/plan-1" in urls
    assert "/v1/user-plans/plan-1/activate" in urls


# contract-test: direct surface=sdks.pip assertions=plans.project-links.encrypted,plans.key-wrappers.contextual,plans.surface.semantic-parity
def test_pip_sdk_plan_add_to_project_encrypts_linked_project_ids(monkeypatch):
    master_key = bytes([3]) * 32
    plan_key = bytes([4]) * 32
    project_key = bytes([5]) * 32
    api_key, material = _create_api_key_material("pip plan parity", master_key)
    plan = {
        "plan_id": "plan-1",
        "version": 1,
        "key_wrappers": [{"key_type": "master", "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, master_key)}],
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
        if url.endswith("/v1/user-plans/plan-1"):
            return FakeResponse({"plan": plan})
        if url.endswith("/v1/user-plans?active_only=False"):
            return FakeResponse({"plans": [plan]})
        if url.endswith("/v1/projects/project-1"):
            return FakeResponse({"project": {"project_id": "project-1", "encrypted_project_key": _encrypt_aes_gcm_bytes(project_key, master_key)}})
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
        plan.update(json)
        return FakeResponse({"plan": {**plan}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key=api_key, device_id="test-device")
    updated = client.plans.add_to_project("plan-1", "project-1")
    assert updated["linked_project_ids"] == ["project-1"]
    assert isinstance(seen_patch["encrypted_linked_project_ids"], str)
    assert seen_patch["linked_project_ids"] == ["project-1"]
    assert [wrapper["key_type"] for wrapper in seen_patch["key_wrappers"]] == ["master", "project"]

    removed = client.plans.remove_from_project("plan-1", "project-1")
    assert removed["linked_project_ids"] == []
    assert seen_patch["linked_project_ids"] == []
    assert [wrapper["key_type"] for wrapper in seen_patch["key_wrappers"]] == ["master"]


# contract-test: direct surface=sdks.pip assertions=plans.surface.semantic-parity,cli.slugs.local-resolution-id-transport,sdk.encryption.local-only
def test_pip_sdk_plan_show_resolves_encrypted_slug_from_raw_list(monkeypatch):
    master_key = bytes([21]) * 32
    plan_key = bytes([22]) * 32
    api_key, material = _create_api_key_material("pip plan slug lookup", master_key)
    slug_metadata = _encrypted_object_slug_metadata("Pip Slug Plan", encryption_key=plan_key, lookup_key=master_key)
    plan = {
        "plan_id": "plan-1",
        "version": 1,
        "key_wrappers": [{"key_type": "master", "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, master_key)}],
        "encrypted_slug": slug_metadata["encrypted_slug"],
        "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
        "encrypted_title": _encrypt_aes_gcm_text("Pip Slug Plan", plan_key),
        "encrypted_linked_project_ids": _encrypt_aes_gcm_text("[]", plan_key),
        "linked_project_ids": [],
        "status": "draft",
        "created_at": 100,
        "updated_at": 100,
    }

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
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url, *, json, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key, device_id="test-device")
    shown = client.plans.show("pip-slug-plan")
    assert shown["plan_id"] == "plan-1"
    assert shown["slug"] == "pip-slug-plan"
