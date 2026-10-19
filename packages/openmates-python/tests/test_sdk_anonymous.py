"""Account-free SDK routing and signup error contract tests."""
# contract-test-file: tooling
import uuid

import pytest
import requests

from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError, OpenMatesSignupRequiredError


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.execution,sdk.surface.semantic-parity
def test_keyless_skill_and_status_share_persisted_identity(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr("openmates.sdk.requests.post", lambda url, **kw: seen.append((url, kw)) or Response({"data": {"results": []}}))
    monkeypatch.setattr("openmates.sdk.requests.get", lambda url, **kw: seen.append((url, kw)) or Response({"active": True, "can_send_text": False}))
    path = tmp_path / "identity"
    first = OpenMates(device_id_path=path)
    second = OpenMates(device_id_path=path)
    first.apps.web.search({"requests": [{"query": "hello"}]})
    assert second.anonymous.status()["can_send_text"] is False
    second.apps.web.search({"requests": [{"query": "cheap operation"}]})
    assert [url for url, _ in seen] == [
        "https://api.openmates.org/v1/anonymous/apps/web/skills/search",
        "https://api.openmates.org/v1/anonymous/free-usage/status",
        "https://api.openmates.org/v1/anonymous/apps/web/skills/search",
    ]
    assert {kw["headers"]["X-OpenMates-Anonymous-ID"] for _, kw in seen} == {path.read_text().strip()}
    assert all("Authorization" not in kw["headers"] for _, kw in seen)


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.execution
def test_anonymous_chat_is_plaintext_ephemeral_and_normalizes_history(monkeypatch):
    seen = []
    monkeypatch.setattr("openmates.sdk.requests.post", lambda url, **kw: seen.append((url, kw)) or Response({"assistant": "Hello!", "chatId": "reply"}))
    result = OpenMates(anonymous_id="guest").chats.send("Hi", history={"messages": [{"role": "assistant", "content": "Earlier", "id": "private-local", "created_at": 123}]}, save_to_account=False)
    url, request = seen[0]
    assert url.endswith("/v1/anonymous/chat/stream")
    assert request["headers"]["Accept"] == "application/json"
    assert request["json"]["message_history"] == [{"role": "assistant", "content": "Earlier", "created_at": 123}]
    assert request["json"]["plaintext_message"] == "Hi"
    assert request["json"]["anonymous_id"] == "guest"
    assert uuid.UUID(request["json"]["client_chat_id"])
    assert uuid.UUID(request["json"]["client_message_id"])
    assert result.content == "Hello!"
    assert result.raw["assistant"] == "Hello!"


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.execution
@pytest.mark.parametrize("option", ["save_to_account", "focus_mode", "memory_ids", "model", "chat_id", "slug", "title", "goal", "goal_title", "project_ids", "team_id", "sender_name", "team_member_mentions", "connected_account_directory", "connected_account_token_ref_inputs"])
def test_private_options_rejected_before_request(monkeypatch, option):
    monkeypatch.setattr("openmates.sdk.requests.post", lambda *a, **kw: pytest.fail("unexpected network request"))
    with pytest.raises(OpenMatesConfigError, match="Anonymous chats"):
        OpenMates(device_id="guest").chats.send("hello", **{option: True})


@pytest.mark.parametrize("identity", ["", "x" * 129, 42])
def test_anonymous_identity_validation(identity):
    with pytest.raises(OpenMatesConfigError, match="anonymous_id"):
        OpenMates(anonymous_id=identity)


def test_explicit_anonymous_ignores_environment_but_rejects_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENMATES_API_KEY", "env-key")
    client = OpenMates(anonymous=True, device_id="guest")
    assert client._api_key is None
    with pytest.raises(OpenMatesConfigError, match="explicit API key"):
        OpenMates(api_key="explicit-key", anonymous=True)
    with pytest.raises(OpenMatesConfigError, match="chats.send"):
        client.apps.ai.ask({"messages": []})
    with pytest.raises(OpenMatesConfigError, match="API key"):
        client.account.info()


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.execution,sdk.surface.semantic-parity
@pytest.mark.parametrize("status", [401, 429])
@pytest.mark.parametrize("from_env", [False, True])
def test_authenticated_failures_never_fall_back_to_guest(monkeypatch, status, from_env):
    seen = []
    if from_env:
        monkeypatch.setenv("OPENMATES_API_KEY", "key")
    monkeypatch.setattr("openmates.sdk.requests.post", lambda url, **kw: seen.append((url, kw)) or Response({"detail": {"reason": "budget_exhausted", "signup_required": True}}, status))
    client = OpenMates(api_key=None if from_env else "key", device_id="guest")
    with pytest.raises(OpenMatesApiError) as exc:
        client.apps.web.search({"requests": []})
    assert type(exc.value) is OpenMatesApiError
    assert len(seen) == 1
    assert "/anonymous/" not in seen[0][0]
    assert seen[0][1]["headers"]["Authorization"] == "Bearer key"


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.signup-required,billing.anonymous.hard-capped-provider-metering
@pytest.mark.parametrize("detail,status", [({"signup_required": True, "reason": "some_limit"}, 429), ({"reason": "budget_exhausted"}, 429), ({"reason": "per_identity_exhausted"}, 429), ({"reason": "inactive"}, 429), ("signup_required", 403)])
def test_free_allowance_exhaustion_is_actionable_typed_error(monkeypatch, detail, status):
    monkeypatch.setattr("openmates.sdk.requests.post", lambda *a, **kw: Response({"detail": detail}, status))
    with pytest.raises(OpenMatesSignupRequiredError) as exc:
        OpenMates(device_id="guest").apps.web.search({"requests": []})
    assert isinstance(exc.value, OpenMatesApiError)
    assert exc.value.signup_required is True
    assert exc.value.code and exc.value.reason
    assert "free" in str(exc.value).lower()
    assert "Create an account" in str(exc.value)
    assert "request failed" not in str(exc.value)


@pytest.mark.parametrize("status", [401, 503, 429])
def test_provider_auth_and_rate_errors_stay_distinct(monkeypatch, status):
    monkeypatch.setattr("openmates.sdk.requests.post", lambda *a, **kw: Response({"detail": {"reason": "provider_unavailable"}}, status))
    with pytest.raises(OpenMatesApiError) as exc:
        OpenMates(device_id="guest").chats.send("hello")
    assert type(exc.value) is OpenMatesApiError
    assert exc.value.status_code == status


def test_network_failure_is_preserved(monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr("openmates.sdk.requests.post", fail)
    with pytest.raises(requests.ConnectionError, match="offline"):
        OpenMates(device_id="guest").chats.send("hello")


@pytest.mark.parametrize("history", [[{"role": "system", "content": "x"}], [{"role": "user", "content": "x" * 20_001}], [{"role": "user", "content": "x"}] * 51, "invalid", [None]])
def test_invalid_history_is_rejected(history):
    with pytest.raises(OpenMatesConfigError):
        OpenMates(device_id="guest").chats.send("hello", history=history)


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.signup-required
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
@pytest.mark.parametrize("body", [b"", b"<html>Service unavailable</html>"])
@pytest.mark.parametrize("operation", ["skill", "chat", "status"])
def test_non_json_failures_preserve_api_error_status(monkeypatch, status, body, operation):
    response = requests.Response()
    response.status_code = status
    response._content = body
    monkeypatch.setattr("openmates.sdk.requests.post", lambda *a, **kw: response)
    monkeypatch.setattr("openmates.sdk.requests.get", lambda *a, **kw: response)
    client = OpenMates(device_id="guest")
    with pytest.raises(OpenMatesApiError) as exc:
        if operation == "skill":
            client.apps.web.search({"requests": []})
        elif operation == "chat":
            client.chats.send("hello")
        else:
            client.anonymous.status()
    assert type(exc.value) is OpenMatesApiError
    assert exc.value.status_code == status
    assert exc.value.data == {}


# contract-test: direct surface=sdks.pip assertions=sdk.anonymous.execution,ai-decide.images.inline
def test_anonymous_decide_forwards_inline_images_state_and_questions(monkeypatch):
    seen = []
    result = {"success": True, "data": {"answers": {"action": {"choice": "retreat"}}}}

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return Response(result)

    monkeypatch.setattr("openmates.sdk.requests.post", post)
    monkeypatch.setattr("openmates.sdk.requests.get", lambda *a, **kw: pytest.fail("Anonymous decide must not preflight status"))
    image_id = "11111111-1111-4111-8111-111111111111"
    payload = {
        "state": {"photo": image_id, "health": 12},
        "questions": {
            "action": {
                "type": "choice", "instructions": "Choose whether to retreat or fight.",
                "criteria": {"retreat": "Avoid defeat", "fight": "Keep fighting"},
            },
        },
        # Transport fixture only; image validation belongs to the backend tests.
        "assets": {
            image_id: {
                "type": "image", "format": "png",
                "data_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1sAAAAASUVORK5CYII=",
            },
        },
    }
    client = OpenMates(anonymous=True, anonymous_id="game-guest", device_id="device")
    assert client.apps.ai.decide(payload) == result
    assert len(seen) == 1
    url, request = seen[0]
    assert url == "https://api.openmates.org/v1/anonymous/apps/ai/skills/decide"
    assert request["json"] == payload
    assert request["headers"]["X-OpenMates-Anonymous-ID"] == "game-guest"
    assert request["headers"]["Accept"] == "application/json"
    assert "Authorization" not in request["headers"]
