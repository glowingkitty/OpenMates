# contract-test-file: tooling

import contextlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import ci_environment as environment


@pytest.mark.parametrize("fault", [None, "limited-token", "denied-list", "extra-provider", "missing-provider", "missing-vapid"])
def test_disposable_provider_probe_uses_initializer_root_and_exact_namespace(monkeypatch, fault):
    monkeypatch.setenv("VAULT_TOKEN", "synthetic-initializer-root")
    calls = []
    class HTTPError(Exception):
        pass
    def response(stage):
        status = 403 if fault == "denied-list" and stage == "list" else 200
        policies = ["api-service"] if fault == "limited-token" else ["root"]
        keys = ["core_server", "hetzner", "vapid"]
        if fault == "extra-provider":
            keys.append("provider-name-must-not-be-printed")
        if fault == "missing-provider":
            keys.remove("hetzner")
        if fault == "missing-vapid":
            keys.remove("vapid")
        def raise_for_status():
            if status != 200:
                raise HTTPError("secret-response-value-must-not-be-printed")
        return SimpleNamespace(status_code=status, raise_for_status=raise_for_status,
            json=lambda: {"data": {"policies": policies, "keys": keys}})
    def get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return response("auth")
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response("list")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=get, request=request))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        if fault:
            with pytest.raises(SystemExit) as error:
                exec(environment.ISOLATED_VAULT_PROVIDER_CHECK, {})
            assert error.value.code == 1
        else:
            exec(environment.ISOLATED_VAULT_PROVIDER_CHECK, {})
    assert all(call[2]["headers"] == {"X-Vault-Token": "synthetic-initializer-root"} for call in calls)
    assert calls[0][1].endswith("/auth/token/lookup-self")
    if fault != "limited-token":
        assert calls[1][0] == "LIST" and calls[1][1].endswith("/kv/metadata/providers")
    text = output.getvalue()
    assert "synthetic-initializer-root" not in text
    assert "provider-name-must-not-be-printed" not in text
    assert "secret-response-value-must-not-be-printed" not in text
    if fault:
        details = json.loads(text)
        if fault == "denied-list":
            assert details["http_status"] == 403 and details["stage"] == "list"
        if fault == "extra-provider":
            assert details["unexpected_count"] == 1
        if fault in {"missing-provider", "missing-vapid"}:
            assert details["missing_count"] == 1
    else:
        assert not text


def test_namespace_inspection_reuses_private_initializer_without_changing_policy(monkeypatch):
    commands = []
    monkeypatch.setattr(environment, "compose", lambda *args: commands.append(args))
    environment.verify_isolated_vault_provider_namespace()
    assert commands == [("run", "--rm", "--no-deps", "vault-init", "python", "-c",
                         environment.ISOLATED_VAULT_PROVIDER_CHECK)]


@pytest.mark.parametrize("stdout", [
    b'{"stage":"list","error_class":"HTTPError","http_status":403,"missing_count":null,"unexpected_count":null}',
    b'private-token-and-response-body',
    b'{"stage":"private-token","error_class":"secret-value!","http_status":"secret","missing_count":false}',
    b'{"stage":{},"error_class":[]}',
    b'{"stage":"list","error_class":"privateToken"}',
    b'private' * 500,
])
def test_probe_failure_reports_only_bounded_classification_without_secret_stderr(monkeypatch, stdout):
    def failed(*args):
        raise subprocess.CalledProcessError(1, args, output=stdout, stderr=b'private-root-token')
    monkeypatch.setattr(environment, "compose", failed)
    with pytest.raises(RuntimeError) as error:
        environment.verify_isolated_vault_provider_namespace()
    text = str(error.value)
    assert text.startswith("Isolated storage Vault provider namespace is unverified (exit=1")
    assert "private" not in text and "secret" not in text
    assert len(text) < 256
    if b'HTTPError' in stdout:
        assert "stage=list" in text and "http_status=403" in text


def test_storage_bootstrap_generates_only_disposable_vapid_pair(monkeypatch):
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    for name, value in {"VAULT_TOKEN": "synthetic-initializer-root", "INTERNAL_API_SHARED_TOKEN": "synthetic-internal",
                        "CI_STORAGE_ACCESS_KEY": "synthetic-storage", "CI_STORAGE_SECRET_KEY": "synthetic-storage-secret"}.items():
        monkeypatch.setenv(name, value)
    writes = {}
    def post(url, **kwargs):
        if "/kv/data/" in url:
            writes[url.rsplit("/", 1)[-1]] = kwargs["json"]["data"]
        return SimpleNamespace(status_code=204, raise_for_status=lambda: None)
    import os
    # Exercise the real bootstrap body with no HTTP, policy or token calls.
    bootstrap = environment.VAULT_INITIALIZE.split("class Client:", 1)[0]
    bootstrap = bootstrap[bootstrap.index("url="):]
    exec(bootstrap, {"os": os, "requests": SimpleNamespace(post=post)})
    assert set(writes) == {"core_server", "hetzner", "vapid"}
    vapid = writes["vapid"]
    private = int.from_bytes(base64.urlsafe_b64decode(vapid["private_key"] + "=" * (-len(vapid["private_key"]) % 4)), "big")
    public = base64.urlsafe_b64decode(vapid["public_key"] + "=" * (-len(vapid["public_key"]) % 4))
    assert ec.derive_private_key(private, ec.SECP256R1()).public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint) == public
    first_public_key = vapid["public_key"]
    exec(bootstrap, {"os": os, "requests": SimpleNamespace(post=post)})
    assert writes["vapid"]["public_key"] != first_public_key
