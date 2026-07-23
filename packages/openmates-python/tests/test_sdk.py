"""OpenMates Python SDK contract tests.

Purpose: verify lazy API-key SDK behavior before implementation.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: SDK must not require email or explicit connect before calls.
Run: python3 -m pytest packages/openmates-python/tests/test_sdk.py
"""

import base64
import hashlib
import json as json_module
import os
import sys
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from openmates import OpenMates, OpenMatesConfigError
from openmates.chat_completion_recovery import seal_recovery_payload


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")


def _encrypt_combined(value: bytes, key: bytes) -> str:
    iv = os.urandom(12)
    return _b64(iv + AESGCM(key).encrypt(iv, value, None))


def _decrypt_combined_bytes(value: str, key: bytes) -> bytes:
    raw = base64.b64decode(value)
    if raw.startswith(b"OM"):
        raw = raw[6:]
    iv, ciphertext = raw[:12], raw[12:]
    return AESGCM(key).decrypt(iv, ciphertext, None)


def _decrypt_combined(value: str, key: bytes) -> str:
    return _decrypt_combined_bytes(value, key).decode("utf-8")


def _wrap_master_key(api_key: str, master_key: bytes) -> dict[str, str]:
    salt = os.urandom(16)
    iv = os.urandom(12)
    wrapping_key = hashlib.pbkdf2_hmac("sha256", api_key.encode("utf-8"), salt, 100_000, dklen=32)
    return {
        "encrypted_key": _b64(AESGCM(wrapping_key).encrypt(iv, master_key, None)),
        "salt": _b64(salt),
        "key_iv": _b64(iv),
    }


def test_missing_api_key_raises_typed_config_error(monkeypatch):
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)

    client = OpenMates()

    with pytest.raises(OpenMatesConfigError):
        client.apps.web.search({"requests": [{"query": "hello"}]})


def test_device_identity_is_injectable_and_stable_without_api_key_material(monkeypatch, tmp_path):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_get(url, *, headers, timeout):
        requests_seen.append(headers["X-OpenMates-Device-Identity"])
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    device_path = tmp_path / "device-id"
    OpenMates(api_key="first-key", device_id_path=device_path).account.info()
    OpenMates(api_key="second-key", device_id_path=device_path).account.info()
    OpenMates(api_key="third-key", device_id="managed-id").account.info()

    assert requests_seen[0] == requests_seen[1] == device_path.read_text().strip()
    assert "first-key" not in device_path.read_text()
    assert requests_seen[2] == "managed-id"


def test_native_app_skill_method_uses_generated_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"results": [{"title": "ok"}]}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    assert not hasattr(client.apps, "run")
    result = client.apps.web.search({"requests": [{"query": "hello"}]})

    assert result == {"success": True, "data": {"results": [{"title": "ok"}]}}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/web/skills/search"
    assert requests[0]["json"] == {"requests": [{"query": "hello"}]}


def test_native_app_skill_method_resolves_async_task_response(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200
        ok = True

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests.append(("POST", url, json, headers))
        return FakeResponse({
            "success": True,
            "data": {"task_id": "task-image-html", "status": "processing"},
            "credits_charged": 0,
        })

    def fake_get(url, *, headers, timeout):
        requests.append(("GET", url, None, headers))
        return FakeResponse({
            "task_id": "task-image-html",
            "status": "completed",
            "result": {
                "html": "<!doctype html><html><body>Generated</body></html>",
                "usage": {"credits_charged": 30},
            },
        })

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    result = client.apps.code.image_to_html({"requests": [{"image_base64": "abc", "mime_type": "image/png"}]})

    assert result == {
        "success": True,
        "data": {
            "html": "<!doctype html><html><body>Generated</body></html>",
            "usage": {"credits_charged": 30},
        },
        "credits_charged": 0,
    }
    assert [(method, url) for method, url, _body, _headers in requests] == [
        ("POST", "https://api.openmates.org/v1/apps/code/skills/image_to_html"),
        ("GET", "https://api.openmates.org/v1/tasks/task-image-html"),
    ]


def test_finance_connected_account_skill_uses_sdk_only_endpoint(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"account_count": 1, "transaction_count": 2}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    result = client.finance.check_accounts(
        {
            "period": "monthly",
            "connected_account_requests": [{"source_ref": "revolut:sandbox"}],
            "csv_statements": [
                {
                    "filename": "cash.csv",
                    "content": "date,description,amount,currency\n2026-07-01,Cafe,-4.5,EUR",
                }
            ],
        },
        connected_account_token_ref_inputs=[
            {
                "connected_account_id": "acct-1",
                "app_id": "finance",
                "provider_id": "revolut_business",
                "allowed_actions": ["read"],
                "action_scope": {"provider": "revolut_business"},
                "refresh_token_envelope": {"refresh_token": "refresh-secret", "provider": "revolut_business"},
            }
        ],
    )

    assert result == {"account_count": 1, "transaction_count": 2}
    assert requests[0]["url"] == "https://api.openmates.org/v1/sdk/connected-account-skills/finance/check_accounts"
    assert requests[0]["json"]["input"]["period"] == "monthly"
    assert requests[0]["json"]["input"]["security"]["prompt_injection_protection"] == "disabled"
    refs = requests[0]["json"]["connected_account_token_ref_inputs"]
    assert refs[0]["provider_id"] == "revolut_business"
    assert "access_token" not in json_module.dumps(requests[0]["json"])


def test_native_app_skill_method_maps_prompt_injection_opt_out(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    result = client.apps.web.search(
        {"requests": [{"query": "hello"}]},
        prompt_injection_protection=False,
    )

    assert result == {"success": True}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/web/skills/search"
    assert requests[0]["json"] == {
        "requests": [{"query": "hello"}],
        "security": {"prompt_injection_protection": "disabled"},
    }


def test_ideabucket_sdk_uses_existing_package_rest_methods(monkeypatch):
    requests = []
    api_key = "sk-api-test"
    master_key = b"\x00" * 32
    wrapper = _wrap_master_key(api_key, master_key)
    encrypted_settings = _encrypt_combined(
        json_module.dumps(
            {
                "processing_prompt": "Python account prompt",
                "processing_times": "09:00,17:00",
            }
        ).encode("utf-8"),
        master_key,
    )

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests.append(("POST", url, json, headers))
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": wrapper})
        if url.endswith("/v1/sdk/ideabucket/buckets/2026-07-18/add"):
            return FakeResponse({"processing_window_id": "2026-07-18", "status": "draft_synced"})
        return FakeResponse({"processing_window_id": "2026-07-18", "status": "sent"})

    def fake_get(url, *, headers, timeout):
        requests.append(("GET", url, None, headers))
        if url.endswith("/v1/sdk/memories?app_id=ideabucket&item_type=processing_settings"):
            return FakeResponse({
                "memories": [{
                    "id": "settings-entry-1",
                    "app_id": "ideabucket",
                    "item_type": "processing_settings",
                    "item_version": 2,
                    "encrypted_item_json": encrypted_settings,
                }]
            })
        return FakeResponse({"processing_window_id": "2026-07-18", "status": "pending"})

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key=api_key)
    assert client.ideabucket.add({"text": "ship", "bucket_id": "2026-07-18"})["status"] == "draft_synced"
    assert client.ideabucket.status("2026-07-18")["status"] == "pending"
    assert client.ideabucket.process("2026-07-18", now=True)["status"] == "sent"

    assert [(method, url) for method, url, _body, _headers in requests] == [
        ("GET", "https://api.openmates.org/v1/sdk/memories?app_id=ideabucket&item_type=processing_settings"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
        ("POST", "https://api.openmates.org/v1/sdk/ideabucket/buckets/2026-07-18/add"),
        ("GET", "https://api.openmates.org/v1/sdk/ideabucket/buckets/2026-07-18"),
        ("POST", "https://api.openmates.org/v1/sdk/ideabucket/buckets/2026-07-18/process"),
    ]
    add_payload = requests[2][2]
    assert "ship" not in json_module.dumps(add_payload)
    assert "Python account prompt" not in json_module.dumps(add_payload)
    server_payload = json_module.loads(_decrypt_combined(add_payload["server_vault_encrypted_processing_payload"], master_key))
    assert server_payload["prompt"] == "Python account prompt"
    assert add_payload["ideabucket_processing_window_id"] == "2026-07-18"
    assert isinstance(add_payload["encrypted_draft_md"], str)
    chat_key = _decrypt_combined_bytes(add_payload["encrypted_chat_key"], master_key)
    assert len(chat_key) == 32
    assert "ship" in _decrypt_combined(add_payload["client_encrypted_future_user_message"], chat_key)
    system_event = json_module.loads(_decrypt_combined(add_payload["client_encrypted_ideabucket_system_event"], chat_key))
    assert system_event["source"] == "openmates_pip_sdk"
    assert requests[4][2] == {"now": True}


def test_api_keys_list_decrypts_labels_and_never_used(monkeypatch):
    api_key = "sk-api-python-list"
    master_key = os.urandom(32)
    wrapper = _wrap_master_key(api_key, master_key)
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url, headers))
        assert url == "https://api.openmates.org/v1/sdk/session"
        return FakeResponse({"user": {"id": "user-1"}, "key_wrapper": wrapper})

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, headers))
        assert url == "https://api.openmates.org/v1/sdk/settings/api-keys"
        return FakeResponse({
            "api_keys": [{
                "id": "key-1",
                "encrypted_name": _encrypt_combined(b"Python Listed Key", master_key),
                "encrypted_key_prefix": _encrypt_combined(b"sk-api-pyth...", master_key),
                "created_at": "2026-07-15T10:00:00Z",
                "last_used_at": None,
                "full_access": True,
                "scopes": {},
                "credit_limit": None,
                "pending_device_count": 1,
            }]
        })

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    result = OpenMates(api_key=api_key).api_keys.list()

    assert result["api_keys"][0]["name"] == "Python Listed Key"
    assert result["api_keys"][0]["last_used_label"] == "Never used"
    assert result["api_keys"][0]["pending_device_count"] == 1
    assert requests_seen[0][2]["Authorization"] == f"Bearer {api_key}"


def test_native_models3d_skill_method_uses_generated_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"status": "processing"}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    assert not hasattr(client.apps.models3d, "generate")
    result = client.apps.models3d.search({"requests": [{"query": "benchy"}]})

    assert result == {"success": True, "data": {"status": "processing"}}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/models3d/skills/search"
    assert requests[0]["json"] == {"requests": [{"query": "benchy"}]}


def test_native_models3d_search_skill_method_uses_generated_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"result_count": 1}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    result = client.apps.models3d.search({"requests": [{"query": "benchy"}]})

    assert result == {"success": True, "data": {"result_count": 1}}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/models3d/skills/search"
    assert requests[0]["json"] == {"requests": [{"query": "benchy"}]}


def test_native_business_company_financials_skill_method_uses_generated_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"result_count": 1}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    result = client.apps.business.company_financials(
        {"companies": [{"query": "CALM"}], "period": "latest_annual"}
    )

    assert result == {"success": True, "data": {"result_count": 1}}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/business/skills/company_financials"
    assert requests[0]["json"] == {"companies": [{"query": "CALM"}], "period": "latest_annual"}


def test_native_design_search_icons_skill_method_uses_generated_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"result_count": 1}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    result = client.apps.design.search_icons({"requests": [{"query": "home", "count": 12}]})

    assert result == {"success": True, "data": {"result_count": 1}}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/design/skills/search_icons"
    assert requests[0]["json"] == {"requests": [{"query": "home", "count": 12}]}


def test_design_icon_export_fetches_openmates_svg_route(monkeypatch, tmp_path):
    requests = []
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><path fill="currentColor" d="M4 12h16v8H4z"/></svg>'

    class FakeResponse:
        status_code = 200
        content = svg
        headers = {"content-type": "image/svg+xml"}

        def json(self):
            return {}

    def fake_get(url, *, headers, timeout):
        requests.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    output_path = tmp_path / "home.svg"
    client = OpenMates(api_key="sk-api-test")
    result = client.design.export_icon(prefix="lucide", name="home", color="#111827", output_path=output_path)

    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/design/icons/iconify/lucide/home.svg"
    assert result["format"] == "svg"
    assert result["content_type"] == "image/svg+xml"
    assert b"#111827" in result["data"]
    assert "#111827" in output_path.read_text(encoding="utf-8")


def test_design_icon_export_png_uses_local_rasterizer(monkeypatch, tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><path fill="currentColor" d="M4 12h16v8H4z"/></svg>'
    png = b"\x89PNG\r\n\x1a\n"
    rasterizer_calls = []

    class FakeResponse:
        status_code = 200
        content = svg
        headers = {"content-type": "image/svg+xml"}

        def json(self):
            return {}

    def fake_get(url, *, headers, timeout):
        return FakeResponse()

    def fake_svg2png(**kwargs):
        rasterizer_calls.append(kwargs)
        return png

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=fake_svg2png))
    output_path = tmp_path / "home.png"
    client = OpenMates(api_key="sk-api-test")
    result = client.design.export_icon(svg_path="/v1/apps/design/icons/iconify/lucide/home.svg", format="png", size=64, output_path=output_path)

    assert result["format"] == "png"
    assert result["content_type"] == "image/png"
    assert result["data"] == png
    assert output_path.read_bytes() == png
    assert rasterizer_calls[0]["output_width"] == 64


def test_application_preview_lifecycle_uses_embed_preview_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
        if url.endswith("/v1/applications/embed-1/preview/start"):
            return FakeResponse({"session_id": "session-1", "preview_url": "https://preview.example/t/token/", "status": "queued", "credits_per_minute": 5})
        if url.endswith("/v1/applications/preview/session-1/open"):
            return FakeResponse({"session_id": "session-1", "status": "running", "events": [], "auto_started": False})
        if url.endswith("/v1/applications/preview/session-1/stop"):
            return FakeResponse({"session_id": "session-1", "status": "stopped", "charged_credits": 5})
        raise AssertionError(f"Unexpected POST: {url}")

    def fake_get(url, *, headers, timeout):
        requests.append({"method": "GET", "url": url, "json": None, "headers": headers})
        if url.endswith("/v1/applications/preview/session-1"):
            return FakeResponse({"session_id": "session-1", "status": "running", "events": [], "auto_started": False})
        raise AssertionError(f"Unexpected GET: {url}")

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    started = client.embeds.preview.start("embed-1", chat_id="chat-1", requested_runtime="svelte")
    waited = client.embeds.preview.start("embed-1", chat_id="chat-1", wait=True, timeout_s=5)
    status = client.embeds.preview.status("session-1")
    opened = client.embeds.preview.open("session-1")
    stopped = client.embeds.preview.stop("session-1")

    assert started["status"] == "queued"
    assert waited["status"] == status["status"] == opened["status"] == "running"
    assert stopped["status"] == "stopped"
    assert [request["method"] for request in requests] == ["POST", "POST", "GET", "GET", "POST", "POST"]
    assert requests[0]["url"] == "https://api.openmates.org/v1/applications/embed-1/preview/start"
    assert requests[0]["json"] == {"chat_id": "chat-1", "requested_runtime": "svelte"}
    assert requests[1]["json"] == {"chat_id": "chat-1"}


def test_task_workflow_app_skill_methods_expose_embed_contracts(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if url.endswith("/v1/apps/tasks/skills/create"):
            return FakeResponse({
                "success": True,
                "data": {
                    "success": True,
                    "app_id": "tasks",
                    "skill_id": "create",
                    "parent_embed_id": "app-skill-use-1",
                    "result_count": 1,
                    "results": [{
                        "type": "task",
                        "parent_app_skill_type": "app_skill_use",
                        "child_embed_id": "task-embed-1",
                        "task_id": "task-1",
                        "short_id": "TASK-1",
                        "title": "Draft checklist",
                        "status": "todo",
                        "assignee": "user",
                    }],
                },
            })
        if url.endswith("/v1/apps/tasks/skills/search"):
            return FakeResponse({
                "success": True,
                "data": {
                    "success": True,
                    "app_id": "tasks",
                    "skill_id": "search",
                    "status": "waiting_for_client",
                    "requires_connected_client": True,
                    "pending_client_search": {"request_id": "task-search-1", "notification_queued": True},
                    "result_count": 0,
                    "results": [],
                },
            })
        if url.endswith("/v1/apps/workflows/skills/create-or-modify"):
            return FakeResponse({
                "success": True,
                "data": {
                    "success": True,
                    "app_id": "workflows",
                    "skill_id": "create-or-modify",
                    "parent_embed_id": "app-skill-use-1",
                    "result_count": 1,
                    "results": [{
                        "type": "workflow",
                        "parent_app_skill_type": "app_skill_use",
                        "child_embed_id": "workflow-embed-1",
                        "workflow_id": "workflow-1",
                        "title": "Morning weather",
                        "status": "draft",
                    }],
                },
            })
        if url.endswith("/v1/apps/workflows/skills/search"):
            return FakeResponse({
                "success": True,
                "data": {
                    "success": True,
                    "app_id": "workflows",
                    "skill_id": "search",
                    "status": "finished",
                    "requires_connected_client": False,
                    "result_count": 2,
                    "results": [
                        {
                            "type": "workflow",
                            "parent_app_skill_type": "app_skill_use",
                            "child_embed_id": "workflow-embed-1",
                            "workflow_id": "workflow-1",
                            "title": "Morning weather",
                            "status": "enabled",
                        },
                        {
                            "type": "workflow",
                            "parent_app_skill_type": "app_skill_use",
                            "child_embed_id": "workflow-embed-2",
                            "workflow_id": "workflow-2",
                            "title": "Weather digest",
                            "status": "draft",
                        },
                    ],
                },
            })
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    task_create = client.apps.tasks.create({"tasks": [{"title": "Draft checklist"}]})
    task_search = client.apps.tasks.search({"query": "checklist"})
    workflow_create = client.apps.workflows.create_or_modify({"title": "Morning weather"})
    workflow_search = client.apps.workflows.search({"query": "weather", "include_temporary": True})

    assert task_create["data"]["parent_embed_id"] == "app-skill-use-1"
    assert task_create["data"]["results"][0]["parent_app_skill_type"] == "app_skill_use"
    assert task_create["data"]["results"][0]["child_embed_id"] == "task-embed-1"
    assert task_search["data"]["status"] == "waiting_for_client"
    assert task_search["data"]["pending_client_search"]["request_id"] == "task-search-1"
    assert task_search["data"]["results"] == []
    assert workflow_create["data"]["results"][0]["child_embed_id"] == "workflow-embed-1"
    assert workflow_search["data"]["status"] == "finished"
    assert workflow_search["data"]["requires_connected_client"] is False
    assert [result["child_embed_id"] for result in workflow_search["data"]["results"]] == [
        "workflow-embed-1",
        "workflow-embed-2",
    ]

    assert [request["url"] for request in requests] == [
        "https://api.openmates.org/v1/apps/tasks/skills/create",
        "https://api.openmates.org/v1/apps/tasks/skills/search",
        "https://api.openmates.org/v1/apps/workflows/skills/create-or-modify",
        "https://api.openmates.org/v1/apps/workflows/skills/search",
    ]
    assert requests[0]["json"] == {"tasks": [{"title": "Draft checklist"}]}
    assert requests[3]["json"] == {"query": "weather", "include_temporary": True}


def test_task_workspace_methods_match_npm_sdk_contract(monkeypatch):
    requests = []
    api_key = "sk-api-test"
    master_key = bytes([9]) * 32
    wrapper = _wrap_master_key(api_key, master_key)
    stored_task = None

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        nonlocal stored_task
        requests.append({"method": "GET", "url": url, "json": None, "headers": headers})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        return FakeResponse({"tasks": [stored_task] if stored_task else []})

    def fake_post(url, *, json, headers, timeout):
        nonlocal stored_task
        requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": wrapper})
        if url.endswith("/v1/user-tasks"):
            assert isinstance(json.get("encrypted_title"), str)
            assert "title" not in json
            stored_task = {**json, "short_id": "TASK-1"}
            return FakeResponse({"task": stored_task})
        if url.endswith("/start-ai"):
            assert isinstance(json.get("plaintext_title"), str)
            stored_task = {**stored_task, "status": "in_progress"}
            return FakeResponse({"task": stored_task})
        return FakeResponse({"task": stored_task})

    def fake_patch(url, *, json, headers, timeout):
        nonlocal stored_task
        requests.append({"method": "PATCH", "url": url, "json": json, "headers": headers})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        stored_task = {**stored_task, **json}
        return FakeResponse({"task": stored_task})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key=api_key)
    created = client.tasks.create({"title": "Draft launch plan", "description": "Use project context"})
    assert created["title"] == "Draft launch plan"
    assert "encrypted" not in created
    assert client.tasks.list(status="todo", chat_id="chat-1", project_id="project-1")[0]["task_id"] == created["task_id"]
    assert client.tasks.update("TASK-1", {"status": "done", "title": "Draft launch plan done"})["title"] == "Draft launch plan done"
    assert client.tasks.start_ai("TASK-1")["status"] == "in_progress"
    created_path = f"/v1/user-tasks/{created['task_id']}"

    assert ("POST", "/v1/sdk/session") in [
        (request["method"], request["url"].replace("https://api.openmates.org", "")) for request in requests
    ]
    assert [
        (request["method"], request["url"].replace("https://api.openmates.org", ""))
        for request in requests
        if request["method"] != "POST" or not request["url"].endswith("/v1/sdk/session")
    ] == [
        ("POST", "/v1/user-tasks"),
        ("GET", "/v1/user-tasks?status=todo&chat_id=chat-1&project_id=project-1"),
        ("GET", "/v1/user-tasks"),
        ("PATCH", created_path),
        ("GET", "/v1/user-tasks"),
        ("POST", f"{created_path}/start-ai"),
    ]
    assert isinstance(requests[1]["json"].get("encrypted_title"), str)


def test_workspace_history_methods_match_npm_sdk_contract(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests.append({"method": "GET", "url": url, "json": None, "headers": headers})
        assert headers["Authorization"] == "Bearer sk-api-test"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/workspace/history?object_type=task&object_id=task-1&limit=5"):
            return FakeResponse({"change_sets": [{"change_set_id": "cs-1"}]})
        if url.endswith("/v1/workspace/history/cs-1"):
            return FakeResponse({"change_set": {"change_set_id": "cs-1"}, "entries": []})
        if url.endswith("/v1/projects/project-1/history?limit=3"):
            return FakeResponse({"entries": [{"entry_id": "che-project"}]})
        raise AssertionError(f"Unexpected GET request: {url}")

    def fake_post(url, *, json, headers, timeout):
        requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
        assert headers["Authorization"] == "Bearer sk-api-test"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/workspace/history/cs-1/undo"):
            return FakeResponse({"undone": True, "change_set_id": "undo-1"})
        if url.endswith("/v1/workflows/wf-1/restore"):
            return FakeResponse({"workflow": {"id": "wf-1"}, "history": {"change_set": {"change_set_id": "cs-restore"}}})
        if url.endswith("/v1/user-tasks/ask") or url.endswith("/v1/projects/ask") or url.endswith("/v1/workflows/ask"):
            return FakeResponse({"applied": True, "change_set_id": "chg-ask", "changed_entries": []})
        raise AssertionError(f"Unexpected POST request: {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    assert client.history.list(object_type="task", object_id="task-1", limit=5) == [{"change_set_id": "cs-1"}]
    assert client.history.show("cs-1") == {"change_set": {"change_set_id": "cs-1"}, "entries": []}
    assert client.history.undo("cs-1") == {"undone": True, "change_set_id": "undo-1"}
    assert client.projects.history("project-1", limit=3) == [{"entry_id": "che-project"}]
    assert client.workflows.restore("wf-1", entry_id="che-workflow", state="before") == {"workflow": {"id": "wf-1"}, "history": {"change_set": {"change_set_id": "cs-restore"}}}
    assert client.tasks.ask("Prepare launch", encrypted_create={"task_id": "task-1"}) == {"applied": True, "change_set_id": "chg-ask", "changed_entries": []}
    assert client.projects.ask("Launch", encrypted_create={"project_id": "project-1"}) == {"applied": True, "change_set_id": "chg-ask", "changed_entries": []}
    assert client.workflows.ask("Rain alert", create={"title": "Rain alert"}) == {"applied": True, "change_set_id": "chg-ask", "changed_entries": []}

    assert [(request["method"], request["url"].replace("https://api.openmates.org", "")) for request in requests] == [
        ("GET", "/v1/workspace/history?object_type=task&object_id=task-1&limit=5"),
        ("GET", "/v1/workspace/history/cs-1"),
        ("POST", "/v1/workspace/history/cs-1/undo"),
        ("GET", "/v1/projects/project-1/history?limit=3"),
        ("POST", "/v1/workflows/wf-1/restore"),
        ("POST", "/v1/user-tasks/ask"),
        ("POST", "/v1/projects/ask"),
        ("POST", "/v1/workflows/ask"),
    ]
    assert requests[2]["json"] == {}
    assert requests[4]["json"] == {"entry_id": "che-workflow", "state": "before"}
    assert requests[5]["json"] == {"instruction": "Prepare launch", "encrypted_create": {"task_id": "task-1"}}
    assert requests[6]["json"] == {"instruction": "Launch", "encrypted_create": {"project_id": "project-1"}}
    assert requests[7]["json"] == {"instruction": "Rain alert", "create": {"title": "Rain alert"}}


def test_workflow_workspace_methods_match_npm_sdk_contract(monkeypatch):
    requests = []
    graph = {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [{"id": "trigger", "type": "manual_trigger", "config": {}}],
        "edges": [],
    }
    workflow = {
        "id": "wf-1",
        "title": "Morning",
        "status": "active",
        "enabled": True,
        "run_content_retention": "last_5",
        "current_version_id": "v1",
        "created_at": 1,
        "updated_at": 2,
        "graph": graph,
    }
    run = {
        "id": "run-1",
        "workflow_id": "wf-1",
        "version_id": "v1",
        "trigger_type": "manual",
        "status": "completed",
        "content_retention_mode": "last_5",
        "content_available": True,
        "content_storage": "durable",
        "node_runs": [],
    }
    template_payload = {
        "template_version": 1,
        "title": "Morning",
        "trigger_template": {"type": "manual_trigger", "config": {}},
        "node_templates": [],
        "edge_templates": [],
        "variables_schema": {},
        "required_capabilities": [],
        "binding_requirements": [],
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def record(method, url, json, headers):
        requests.append({"method": method, "url": url, "json": json, "headers": headers})
        if "/v1/workflows/template-projections/" in url:
            assert "Authorization" not in headers
        else:
            assert headers["Authorization"] == "Bearer sk-api-test"
        assert headers["X-OpenMates-SDK"] == "pip"

    def fake_get(url, *, headers, timeout):
        record("GET", url, None, headers)
        if url.endswith("/v1/workflows"):
            return FakeResponse({"workflows": [workflow]})
        if url.endswith("/v1/workflows/temporary"):
            return FakeResponse({"workflows": [{**workflow, "id": "wf-temp", "lifecycle": "temporary"}]})
        if url.endswith("/v1/workflows/capabilities"):
            return FakeResponse({"capabilities": [{"id": "weather:forecast", "type": "app_skill", "title": "Weather forecast", "enabled": True}]})
        if url.endswith("/v1/workflows/wf-1"):
            return FakeResponse({"workflow": workflow})
        if url.endswith("/v1/workflows/wf-1/runs"):
            return FakeResponse({"runs": [run]})
        if url.endswith("/v1/workflows/wf-1/runs/run-1"):
            return FakeResponse({"run": {**run, "node_runs": [{"id": "node-run-1", "output_summary": {"forecast": "rain"}}]}})
        if url.endswith("/v1/workflows/template-projections/tpl-1"):
            return FakeResponse({"template_id": "tpl-1", "ciphertext": "opaque-ciphertext", "projection_schema_version": 1})
        if url.endswith("/v1/workflows/input/session-1"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "executed", "event_cursor": 4, "undo_available": True, "events": []}})
        if url.endswith("/v1/workflows/input/session-1/events?after_event_id=2"):
            return FakeResponse({"events": [{"id": "event-3", "event_id": 3, "type": "validation_passed", "status": "ok"}]})
        raise AssertionError(f"Unexpected GET: {url}")

    def fake_post(url, *, json, headers, timeout):
        record("POST", url, json, headers)
        if url.endswith("/v1/workflows/validate"):
            return FakeResponse({"validation": {"draft_valid": True, "enable_ready": False, "diagnostics": []}})
        if url.endswith("/v1/workflows/yaml") or url.endswith("/v1/workflows/wf-1/yaml"):
            return FakeResponse({"workflow": workflow, "validation": {"draft_valid": True, "enable_ready": True, "diagnostics": []}})
        if url.endswith("/v1/workflows"):
            return FakeResponse({"workflow": {**workflow, **json}})
        if url.endswith("/v1/workflows/wf-1/enable"):
            return FakeResponse({"workflow": {**workflow, "enabled": True}})
        if url.endswith("/v1/workflows/wf-1/disable"):
            return FakeResponse({"workflow": {**workflow, "enabled": False}})
        if url.endswith("/v1/workflows/wf-1/keep"):
            return FakeResponse({"workflow": workflow})
        if url.endswith("/v1/workflows/wf-1/run"):
            assert headers["Idempotency-Key"] == "stable-run-1"
            return FakeResponse({"run": {**run, "trigger_type": json["mode"], "content_storage": "ephemeral"}})
        if url.endswith("/v1/workflows/wf-1/runs/run-1/cancel"):
            return FakeResponse({"run_id": "run-1", "status": "cancellation_requested"})
        if url.endswith("/v1/workflows/wf-1/runs/run-1/respond"):
            return FakeResponse({"run": run})
        if url.endswith("/v1/workflows/wf-1/template-projection/revoke"):
            return FakeResponse({"template_id": "tpl-1", "revoked_at": 1000})
        if url.endswith("/v1/workflows/wf-1/template-projection/unrevoke"):
            return FakeResponse({"template_id": "tpl-1", "revoked_at": None})
        if url.endswith("/v1/workflows/wf-1/binding-requirements/complete"):
            return FakeResponse({"workflow_id": "wf-1", "completed": True})
        if url.endswith("/v1/share/short-url"):
            return FakeResponse({"success": True, "expires_at": 999})
        if url.endswith("/v1/workflows/template-import"):
            return FakeResponse({"workflow": {**workflow, "id": "wf-imported", "binding_requirements": []}})
        if url.endswith("/v1/workflows/input"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "executed", "event_cursor": 4, "undo_available": True}})
        if url.endswith("/v1/workflows/input/session-1/follow-up"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "executed", "event_cursor": 7, "undo_available": True}})
        if url.endswith("/v1/workflows/input/session-1/stop"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "stopped", "event_cursor": 8, "undo_available": True}})
        if url.endswith("/v1/workflows/input/session-1/undo"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "undone", "event_cursor": 9, "undo_available": False}})
        raise AssertionError(f"Unexpected POST: {url}")

    def fake_patch(url, *, json, headers, timeout):
        record("PATCH", url, json, headers)
        return FakeResponse({"workflow": {**workflow, **json}})

    def fake_put(url, *, json, headers, timeout):
        record("PUT", url, json, headers)
        return FakeResponse({"template_id": json["template_id"], "source_version": json["source_version"], "updated_at": 123})

    def fake_delete(url, *, json, headers, timeout):
        record("DELETE", url, json, headers)
        if url.endswith("/v1/share/short-url/Abc123XY"):
            return FakeResponse({"success": True, "revoked_at": 1000})
        if url.endswith("/v1/workflows/wf-1"):
            return FakeResponse({"deleted": True})
        raise AssertionError(f"Unexpected DELETE: {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.put", fake_put)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key="sk-api-test")
    assert client.workflows.list()[0]["id"] == "wf-1"
    assert client.workflows.temporary()[0]["id"] == "wf-temp"
    assert client.workflows.capabilities()[0]["id"] == "weather:forecast"
    assert client.workflows.validate_yaml("title: Morning\n")["draft_valid"] is True
    assert client.workflows.create_from_yaml("title: Morning\n")["workflow"]["id"] == "wf-1"
    assert client.workflows.update_from_yaml("wf-1", "title: Updated\n")["workflow"]["id"] == "wf-1"
    assert client.workflows.create(title="Morning", graph=graph, enabled=True, run_content_retention="none", lifecycle="temporary", source="chat", source_chat_id="chat-1", created_by_assistant=True)["source_chat_id"] == "chat-1"
    assert client.workflows.get("wf-1")["id"] == "wf-1"
    assert client.workflows.update("wf-1", description="Updated desc", enabled=False, run_content_retention="last_5")["description"] == "Updated desc"
    assert client.workflows.enable("wf-1")["enabled"] is True
    assert client.workflows.disable("wf-1")["enabled"] is False
    assert client.workflows.keep("wf-1")["id"] == "wf-1"
    assert client.workflows.run("wf-1", idempotency_key="stable-run-1", mode="test", input_data={"dry": True})["content_storage"] == "ephemeral"
    assert client.workflows.runs("wf-1")[0]["id"] == "run-1"
    assert client.workflows.run_detail("wf-1", "run-1")["node_runs"][0]["output_summary"]["forecast"] == "rain"
    assert client.workflows.cancel_run("wf-1", "run-1")["status"] == "cancellation_requested"
    assert client.workflows.respond("wf-1", "run-1", "ask", {"answer": "Berlin"})["status"] == "completed"
    assert client.workflows.upsert_template_projection(workflow_id="wf-1", template_id="tpl-1", source_version=2, ciphertext="opaque-ciphertext", ciphertext_checksum="sha256:abc", owner_wrapped_key="wrapped-key", projection_schema_version=1)["updated_at"] == 123
    assert client.workflows.get_public_template_projection("tpl-1")["ciphertext"] == "opaque-ciphertext"
    assert client.workflows.revoke_template_projection("wf-1")["revoked_at"] == 1000
    assert client.workflows.unrevoke_template_projection("wf-1")["revoked_at"] is None
    assert client.workflows.complete_imported_binding("wf-1", binding_type="connected_account", node_id="weather")["completed"] is True
    assert client.workflows.create_template_short_url(token="Abc123XY", encrypted_url="opaque-url", template_id="tpl-1", ttl_seconds=3600)["expires_at"] == 999
    assert client.workflows.revoke_short_url("Abc123XY")["revoked_at"] == 1000
    assert client.workflows.import_template(template_payload)["id"] == "wf-imported"
    assert client.workflows.delete("wf-1", confirmed=True)["deleted"] is True
    assert client.workflows.start_input(text="alert me if it rains", selected_project_id="project-1")["session_id"] == "session-1"
    assert client.workflows.input_session("session-1")["status"] == "executed"
    assert client.workflows.input_events("session-1", after_event_id=2)[0]["type"] == "validation_passed"
    assert client.workflows.follow_up_input("session-1", "weekdays only")["event_cursor"] == 7
    assert client.workflows.stop_input("session-1")["status"] == "stopped"
    assert client.workflows.undo_input("session-1")["status"] == "undone"

    assert [(request["method"], request["url"].replace("https://api.openmates.org", "")) for request in requests[:8]] == [
        ("GET", "/v1/workflows"),
        ("GET", "/v1/workflows/temporary"),
        ("GET", "/v1/workflows/capabilities"),
        ("POST", "/v1/workflows/validate"),
        ("POST", "/v1/workflows/yaml"),
        ("POST", "/v1/workflows/wf-1/yaml"),
        ("POST", "/v1/workflows"),
        ("GET", "/v1/workflows/wf-1"),
    ]
    assert requests[6]["json"] == {
        "title": "Morning",
        "graph": graph,
        "enabled": True,
        "run_content_retention": "none",
        "lifecycle": "temporary",
        "source": "chat",
        "created_by_assistant": True,
        "source_chat_id": "chat-1",
    }
    assert requests[8]["json"] == {"description": "Updated desc", "enabled": False, "run_content_retention": "last_5"}


def test_new_chat_defaults_to_non_persistent(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "persistent": False,
                "response": {
                    "content": "hi",
                    "raw": {"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
                },
            }

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    response = client.chats.send("hello")

    assert response.content == "hi"
    assert requests[0]["url"] == "https://api.openmates.org/v1/sdk/chats"
    assert requests[0]["json"]["save_to_account"] is False


def test_chat_send_rewrites_remember_message_references(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": {"content": "ok"}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    client.chats.send(
        "Remember my message @abc12345",
        history=[{"id": "abc12345-0000-4000-8000-000000000000", "role": "user", "content": "Earlier\nWith [embed](embed:ref-1)"}],
    )

    assert requests[0]["json"]["message"] == "Remember my earlier message:\n\n> Earlier\n> With [embed](embed:ref-1)"
    assert requests[0]["json"]["history"][0]["content"] == "Earlier\nWith [embed](embed:ref-1)"


def test_saved_chat_preflights_epoch_one_encrypted_recovery_material(monkeypatch):
    api_key = "sk-api-python-saved"
    key_wrapper = _wrap_master_key(api_key, os.urandom(32))
    requests_seen = []
    task_id = "77777777-7777-4777-8777-777777777777"
    job_id = "88888888-8888-4888-8888-888888888888"
    claim_count = 0

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        nonlocal claim_count
        requests_seen.append({"url": url, "json": json})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({
                "user": {"id": "11111111-1111-4111-8111-111111111111"},
                "key_wrapper": key_wrapper,
            })
        if url.endswith("/v1/sdk/chats"):
            return FakeResponse({"persistent": True, "chat_id": json["chat_id"], "task_id": task_id})
        if url.endswith(f"/{task_id}/claim"):
            claim_count += 1
            if claim_count == 1:
                response = FakeResponse({"detail": {"error": "recovery_job_not_found"}})
                response.status_code = 404
                return response
            saved = next(request["json"] for request in requests_seen if request["url"].endswith("/v1/sdk/chats"))
            assistant_message_id = task_id
            plaintext = json_module.dumps({
                "assistant_message_id": assistant_message_id,
                "category": "general",
                "chat_id": saved["chat_id"],
                "content": "saved reply",
                "job_id": job_id,
                "key_version": 1,
                "model_name": "test-model",
                "turn_id": saved["turn_id"],
            }, sort_keys=True, separators=(",", ":")).encode()
            envelope = seal_recovery_payload(
                plaintext,
                recovery_public_key=saved["recovery_public_key"],
                owner_id="11111111-1111-4111-8111-111111111111",
                chat_id=saved["chat_id"],
                turn_id=saved["turn_id"],
                job_id=job_id,
                assistant_message_id=assistant_message_id,
                key_version=1,
            )
            return FakeResponse({
                "job_id": job_id,
                "state": "LEASED",
                "lease_token": "lease-token",
                "lease_generation": 1,
                "sealed_payload": json_module.dumps(envelope),
                "chat_id": saved["chat_id"],
                "turn_id": saved["turn_id"],
                "assistant_message_id": assistant_message_id,
                "chat_key_version": 1,
            })
        assert url.endswith(f"/{task_id}/persist")
        assert "saved reply" not in json_module.dumps(json)
        assert json["expected_messages_v"] == 1
        assert isinstance(json["encrypted_assistant_message"]["encrypted_content"], str)
        return FakeResponse({"job_id": job_id, "state": "TERMINAL", "committed_messages_v": 2})

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key, device_id="test-device-id")
    response = client.chats.send(
        "save this",
        save_to_account=True,
        title="Saved pip chat",
        recovery_poll_interval_seconds=0.001,
    )
    assert response.content == "saved reply"

    assert [request["url"] for request in requests_seen] == [
        "https://api.openmates.org/v1/sdk/session",
        "https://api.openmates.org/v1/sdk/chats",
        f"https://api.openmates.org/v1/sdk/chats/recovery/{task_id}/claim",
        f"https://api.openmates.org/v1/sdk/chats/recovery/{task_id}/claim",
        f"https://api.openmates.org/v1/sdk/chats/recovery/{task_id}/persist",
    ]
    saved = requests_seen[1]["json"]
    assert saved["save_to_account"] is True
    assert saved["protocol_version"] == 1
    assert len(saved["chat_id"]) == 36
    assert len(saved["turn_id"]) == 36
    assert len(saved["message_id"]) == 36
    assert saved["chat_key_version"] == 1
    assert isinstance(saved["encrypted_chat_key"], str)
    assert len(saved["recovery_public_key"]) == 43
    assert "chat_key" not in saved
    assert "master_key" not in saved
    assert isinstance(saved["encrypted_user_message"]["encrypted_content"], str)
    assert isinstance(saved["encrypted_chat_metadata"]["encrypted_title"], str)


def test_saved_chat_times_out_when_recovery_job_stays_unavailable(monkeypatch):
    api_key = "sk-api-python-timeout"
    key_wrapper = _wrap_master_key(api_key, os.urandom(32))

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({
                "user": {"id": "11111111-1111-4111-8111-111111111111"},
                "key_wrapper": key_wrapper,
            })
        if url.endswith("/v1/sdk/chats"):
            return FakeResponse({"task_id": "77777777-7777-4777-8777-777777777777"})
        response = FakeResponse({"detail": {"error": "recovery_job_not_found"}})
        response.status_code = 404
        return response

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    client = OpenMates(api_key=api_key, device_id="test-device-id")
    with pytest.raises(OpenMatesConfigError, match="Timed out waiting for saved chat recovery"):
        client.chats.send(
            "save this",
            save_to_account=True,
            recovery_poll_interval_seconds=0.001,
            recovery_timeout_seconds=0.005,
        )


@pytest.mark.parametrize("poll_interval", [0, -1, float("inf")])
def test_saved_chat_rejects_nonpositive_or_unbounded_poll_interval(poll_interval):
    client = OpenMates(api_key="sk-api-test", device_id="test-device")
    with pytest.raises(OpenMatesConfigError, match="finite and positive"):
        client.chats._poll_recovery_claim(
            "task-id",
            timeout_seconds=1,
            poll_interval_seconds=poll_interval,
        )


def test_saved_chat_fails_before_send_without_sdk_key_material(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"key_wrapper": {}}

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(url)
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    with pytest.raises(OpenMatesConfigError, match="API-key-wrapped master key material"):
        client.chats.send("save this", save_to_account=True)

    assert requests_seen == ["https://api.openmates.org/v1/sdk/session"]


def test_new_chat_can_include_focus_mode(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "response": {
                    "content": "focused",
                    "raw": {"choices": [{"message": {"role": "assistant", "content": "focused"}}]},
                }
            }

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    response = client.chats.send("research this", focus_mode={"app_id": "web", "focus_mode_id": "research"})

    assert response.content == "focused"
    assert requests[0]["json"]["focus_mode"] == {"app_id": "web", "focus_mode_id": "research"}


def test_lists_latest_encrypted_account_chats(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chats": [{"id": "chat-1", "encrypted_title": "ciphertext"}]}

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    chats = client.chats.list(limit=3)

    assert chats == [{"id": "chat-1", "encrypted_title": "ciphertext"}]
    assert requests_seen[0]["url"] == "https://api.openmates.org/v1/sdk/chats?limit=3&offset=0"
    assert requests_seen[0]["headers"]["X-OpenMates-SDK"] == "pip"


def test_lazily_unwraps_api_key_session_and_decrypts_chat_metadata(monkeypatch):
    api_key = "sk-api-python-test"
    master_key = os.urandom(32)
    chat_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    encrypted_chat_key = _encrypt_combined(chat_key, master_key)
    encrypted_title = _encrypt_combined(b"Decrypted Python SDK chat", chat_key)
    encrypted_summary = _encrypt_combined(b"Encrypted Python summary", chat_key)
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, None))
        assert headers["Authorization"] == f"Bearer {api_key}"
        return FakeResponse({
            "chats": [{
                "id": "chat-1",
                "encrypted_chat_key": encrypted_chat_key,
                "encrypted_title": encrypted_title,
                "encrypted_chat_summary": encrypted_summary,
            }]
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url, json))
        assert headers["Authorization"] == f"Bearer {api_key}"
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key, device_id="test-device-id")
    chats = client.chats.list(limit=1)

    assert chats[0]["title"] == "Decrypted Python SDK chat"
    assert chats[0]["chat_summary"] == "Encrypted Python summary"
    assert chats[0]["encrypted_title"] == encrypted_title
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats?limit=1&offset=0", None),
        ("POST", "https://api.openmates.org/v1/sdk/session", {"sdk_name": "pip", "device_identity": "test-device-id"}),
    ]


def test_searches_decrypted_chat_metadata_locally(monkeypatch):
    api_key = "sk-api-python-search"
    master_key = os.urandom(32)
    madrid_chat_key = os.urandom(32)
    berlin_chat_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    requests_seen = []
    chats = [
        {
            "id": "chat-madrid",
            "encrypted_chat_key": _encrypt_combined(madrid_chat_key, master_key),
            "encrypted_title": _encrypt_combined(b"Madrid itinerary", madrid_chat_key),
        },
        {
            "id": "chat-berlin",
            "encrypted_chat_key": _encrypt_combined(berlin_chat_key, master_key),
            "encrypted_title": _encrypt_combined(b"Berlin itinerary", berlin_chat_key),
        },
    ]

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url))
        return FakeResponse({"chats": chats})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url))
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    results = client.chats.search("Madrid")

    assert [chat["id"] for chat in results] == ["chat-madrid"]
    assert results[0]["title"] == "Madrid itinerary"
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats?limit=0&offset=0"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
    ]


def test_load_decrypts_chat_messages_client_side(monkeypatch):
    api_key = "sk-api-python-load"
    master_key = os.urandom(32)
    chat_key = os.urandom(32)
    embed_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    encrypted_chat_key = _encrypt_combined(chat_key, master_key)
    encrypted_title = _encrypt_combined(b"Loaded Python SDK chat", chat_key)
    encrypted_content = _encrypt_combined(b"Hello from encrypted Python storage", chat_key)
    encrypted_sender = _encrypt_combined(b"OpenMates", chat_key)
    encrypted_embed_key = _encrypt_combined(embed_key, master_key)
    encrypted_embed_type = _encrypt_combined(b"math.calculate", embed_key)
    encrypted_embed_content = _encrypt_combined(b'{"result": 4}', embed_key)
    encrypted_embed_preview = _encrypt_combined(b"2 + 2 = 4", embed_key)
    hashed_embed_id = hashlib.sha256(b"embed-1").hexdigest()
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url))
        return FakeResponse({
            "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": encrypted_title},
            "messages": [{"id": "message-1", "encrypted_content": encrypted_content, "encrypted_sender_name": encrypted_sender}],
            "embeds": [{
                "embed_id": "embed-1",
                "encrypted_type": encrypted_embed_type,
                "encrypted_content": encrypted_embed_content,
                "encrypted_text_preview": encrypted_embed_preview,
            }],
            "embed_keys": [{"hashed_embed_id": hashed_embed_id, "key_type": "master", "encrypted_embed_key": encrypted_embed_key}],
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url))
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    loaded = client.chats.load("chat-1")

    assert loaded["chat"]["title"] == "Loaded Python SDK chat"
    assert loaded["messages"][0]["content"] == "Hello from encrypted Python storage"
    assert loaded["messages"][0]["sender_name"] == "OpenMates"
    assert loaded["messages"][0]["encrypted_content"] == encrypted_content
    assert loaded["embeds"][0]["type"] == "math.calculate"
    assert loaded["embeds"][0]["content"] == {"result": 4}
    assert loaded["embeds"][0]["text_preview"] == "2 + 2 = 4"
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats/chat-1"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
    ]


def test_chat_messages_fork_and_rewind_helpers_preserve_encrypted_payloads(monkeypatch):
    api_key = "sk-api-test"
    master_key = os.urandom(32)
    chat_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    encrypted_chat_key = _encrypt_combined(chat_key, master_key)
    encrypted_title = _encrypt_combined(b"Source chat", chat_key)
    encrypted_question = _encrypt_combined(b"First question", chat_key)
    encrypted_answer = _encrypt_combined(b"First answer", chat_key)
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, None))
        if url == "https://api.openmates.org/v1/sdk/chats/chat-1/messages?direction=latest&limit=30":
            return FakeResponse({
                "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": encrypted_title, "messages_v": 2},
                "messages": [
                    {"client_message_id": "user-1", "chat_id": "chat-1", "role": "user", "encrypted_content": encrypted_question, "created_at": 10},
                    {"client_message_id": "assistant-1", "chat_id": "chat-1", "role": "assistant", "encrypted_content": encrypted_answer, "user_message_id": "user-1", "created_at": 20},
                ],
                "has_more_before": True,
                "server_message_count": 200,
            })
        assert url == "https://api.openmates.org/v1/sdk/chats/chat-1"
        return FakeResponse({
            "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": encrypted_title, "messages_v": 2},
            "messages": [
                {"client_message_id": "user-1", "chat_id": "chat-1", "role": "user", "encrypted_content": encrypted_question, "created_at": 10},
                {"client_message_id": "assistant-1", "chat_id": "chat-1", "role": "assistant", "encrypted_content": encrypted_answer, "user_message_id": "user-1", "created_at": 20},
            ],
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url, json))
        if url == "https://api.openmates.org/v1/sdk/session":
            return FakeResponse({"key_wrapper": key_wrapper})
        if url == "https://api.openmates.org/v1/sdk/chats/chat-1/fork":
            assert "First question" not in json_module.dumps(json)
            assert "First answer" not in json_module.dumps(json)
            assert len(json["encrypted_messages"]) == 2
            return FakeResponse({"success": True, "chat_id": json["new_chat_id"], "copied_message_count": 2, "messages_v": 2})
        if url == "https://api.openmates.org/v1/sdk/chats/chat-1/rewind":
            assert json == {
                "protocol_version": 1,
                "to_message_id": "user-1",
                "expected_messages_v": 2,
                "dry_run": True,
                "confirm_destructive": False,
            }
            return FakeResponse({"success": True, "dry_run": True, "chat_id": "chat-1", "planned_deleted_message_count": 1, "messages_v": 2})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    listed = client.chats.messages(chat_id="chat-1")
    assert listed["messages"][0]["content"] == "First question"
    assert listed["messages"][1]["preview"] == "First answer"
    assert listed["has_more_before"] is True
    assert listed["server_message_count"] == 200
    forked = client.chats.fork(chat_id="chat-1", from_message_id="assistant-1", title="Forked")
    assert forked["copied_message_count"] == 2
    rewind = client.chats.rewind(chat_id="chat-1", to_message_id="user-1", dry_run=True)
    assert rewind["dry_run"] is True

    assert [(method, url) for method, url, _body in requests_seen] == [
        ("GET", "https://api.openmates.org/v1/sdk/chats/chat-1/messages?direction=latest&limit=30"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
        ("GET", "https://api.openmates.org/v1/sdk/chats/chat-1"),
        ("POST", "https://api.openmates.org/v1/sdk/chats/chat-1/fork"),
        ("GET", "https://api.openmates.org/v1/sdk/chats/chat-1"),
        ("POST", "https://api.openmates.org/v1/sdk/chats/chat-1/rewind"),
    ]


def test_chat_list_defaults_to_10_and_limit_zero_requests_all(monkeypatch):
    urls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chats": []}

    def fake_get(url, *, headers, timeout):
        urls.append(url)
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    client.chats.list()
    client.chats.list(limit=0)

    assert urls == [
        "https://api.openmates.org/v1/sdk/chats?limit=10&offset=0",
        "https://api.openmates.org/v1/sdk/chats?limit=0&offset=0",
    ]


def test_chat_messages_all_true_uses_full_history_route(monkeypatch):
    api_key = "sk-api-python-all"
    master_key = os.urandom(32)
    chat_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    encrypted_chat_key = _encrypt_combined(chat_key, master_key)
    encrypted_content = _encrypt_combined(b"Full history message", chat_key)
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url))
        assert url == "https://api.openmates.org/v1/sdk/chats/chat-1"
        return FakeResponse({
            "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key},
            "messages": [{"client_message_id": "message-1", "chat_id": "chat-1", "role": "assistant", "encrypted_content": encrypted_content, "created_at": 1}],
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url))
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    result = OpenMates(api_key=api_key).chats.messages(chat_id="chat-1", all=True)

    assert result["messages"][0]["content"] == "Full history message"
    assert result["has_more_before"] is False
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats/chat-1"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
    ]


def test_named_cli_parity_namespaces_use_sdk_routes(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True, "suggestions": ["next"]}

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        return FakeResponse()

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    assert not hasattr(client.apps, "run")
    assert not hasattr(client, "newsletter")
    assert not hasattr(client.notifications, "set_email")
    assert not hasattr(client.notifications, "set_backup_reminder")
    assert not hasattr(client.notifications, "stream")
    client.account.info()
    client.account.set_timezone("Europe/Berlin")
    client.chats.search("Madrid", limit=5)
    client.chats.load("chat-1")
    client.settings.set_dark_mode(True)
    client.billing.list_invoices()
    client.docs.search("sdk")
    client.embeds.versions("embed-1")
    client.notifications.list(limit=2)
    client.reminders.list()
    client.learning_mode.status()
    client.learning_mode.enable(age_group="16_18", passcode="teach-1234")
    client.learning_mode.disable("teach-1234")
    client.inspirations.list(language="de")
    client.new_chat_suggestions.list(limit=4)

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/account"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/account/timezone"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats?limit=0&offset=0"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats/chat-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/settings/dark-mode"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/billing/invoices"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/docs/search?q=sdk"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/embeds/embed-1/versions"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/notifications?limit=2"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/reminders"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/learning-mode"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/learning-mode/enable"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/learning-mode/disable"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/inspirations?lang=de"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/new-chat-suggestions?limit=4"},
    ]


def test_previously_blocked_sdk_surfaces_route_to_concrete_endpoints(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"ok"

        def __init__(self, payload=None):
            self._payload = payload or {"ok": True, "memories": [], "suggestions": [], "embed_keys": []}

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/v1/sdk/chats/chat-1"):
            return FakeResponse({"chat": {"id": "chat-1"}, "messages": []})
        return FakeResponse()

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    client.chats.follow_ups("chat-1")
    client.chats.export("chat-1")
    client.account.list_interests()
    client.memories.types(app_id="code")
    client.billing.usage_overview(granularity="monthly", months=2)
    client.billing.usage_export()
    client.billing.create_bank_transfer_order(110000)
    client.embeds.show("embed-1")
    with pytest.raises(OpenMatesConfigError, match="must start with OMCA1"):
        client.connected_accounts.import_account(payload="invalid", passcode="123456")
    client.feedback.assistant_response(rating=5)
    client.benchmark.estimate({"suite": "quick"})
    with pytest.raises(OpenMatesConfigError, match="not available through the API-key SDK yet"):
        client.settings.share_debug_logs(confirmed=True)

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats/chat-1"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats/chat-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/chats/chat-1/export"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/account/topic-preferences"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/memories/types?app_id=code"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/billing/usage/overview?granularity=monthly&months=2"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/billing/usage/export"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/billing/bank-transfer-orders"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/embeds/embed-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/feedback/assistant-response"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/benchmark/estimate"},
    ]


def test_destructive_sdk_operations_require_confirmation():
    client = OpenMates(api_key="sk-api-test")

    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.chats.delete("chat-1")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.chats.rewind(chat_id="chat-1", to_message_id="message-1")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.chats.retry(chat_id="chat-1")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.memories.delete("memory-1")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.embeds.restore_version("embed-1", 1)
