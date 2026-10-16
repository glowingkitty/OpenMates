"""Keep existing production passkeys and their encryption derivation usable."""

import ast
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def rp_id(monkeypatch):
    monkeypatch.delenv("WEBAUTHN_RP_ID", raising=False)
    path = Path(__file__).parents[1] / "core/api/app/routes/auth_routes/auth_passkey.py"
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_rp_id_from_request")
    namespace = {"Request": object, "os": os}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return lambda headers: namespace[function.name](SimpleNamespace(headers=headers))


# contract-test: direct surface=rest_api assertions=auth.passkey.origin-prf-bound
def test_existing_apex_passkey_keeps_its_rp_and_prf_input_on_app_subdomain(rp_id):
    old = rp_id({"Origin": "https://openmates.org"})
    new = rp_id({"Origin": "https://app.openmates.org"})
    assert old == new == "openmates.org"
    assert hashlib.sha256(old.encode()).digest()[:32] == hashlib.sha256(new.encode()).digest()[:32]


# contract-test: direct surface=rest_api assertions=auth.passkey.origin-prf-bound
@pytest.mark.parametrize("origin", ["https://app.dev.openmates.org", "https://chat.example.test", "https://app.openmates.org.attacker.test", "https://notopenmates.org"])
def test_other_domains_do_not_share_the_production_rp(rp_id, origin):
    from urllib.parse import urlparse
    assert rp_id({"Origin": origin}) == urlparse(origin).hostname


# contract-test: direct surface=rest_api assertions=auth.passkey.origin-prf-bound
def test_referer_fallback_preserves_production_rp(rp_id):
    assert rp_id({"Referer": "https://app.openmates.org/"}) == "openmates.org"
    assert rp_id({"Origin": "http://127.0.0.1:5173"}) == "localhost"
