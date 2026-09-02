# backend/tests/test_auth_session_security_isolation.py
# Contract tests for logical-session security isolation.
# These tests keep country risk state separate from account profile data and
# prove refresh rotation, encrypted display metadata, and device identity do
# not leak authentication effects across sibling sessions.

import asyncio
import hashlib

from backend.core.api.app.routes.auth_routes import auth_common
from backend.core.api.app.utils import device_fingerprint


class FakeCache:
    def __init__(self, values):
        self.values = values

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True


class FakeRequest:
    headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/140.0"}
    client = None


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


# contract-test: direct surface=rest_api assertions=auth.session.isolation,auth.session.risk-reauth
def test_country_risk_uses_only_the_current_logical_session():
    cache = FakeCache({
        "user_tokens:user-1": {
            token_hash("browser-token"): {"security_country_code": "DE"},
            token_hash("cli-token"): {"security_country_code": "FI"},
        },
    })

    browser = asyncio.run(auth_common.get_session_security_country(cache, "user-1", "browser-token"))
    cli = asyncio.run(auth_common.get_session_security_country(cache, "user-1", "cli-token"))

    assert browser == "DE"
    assert cli == "FI"
    assert auth_common.session_country_changed(cli, "FI") is False
    assert auth_common.session_country_changed(cli, "US") is True


# contract-test: direct surface=rest_api assertions=auth.session.isolation,auth.session.risk-reauth
def test_country_update_mutates_only_the_target_session_and_preserves_encrypted_meta():
    browser_hash = token_hash("browser-token")
    cli_hash = token_hash("cli-token")
    cache = FakeCache({
        "user_tokens:user-1": {
            browser_hash: {"security_country_code": "DE", "encrypted_meta": "opaque-browser"},
            cli_hash: {"security_country_code": "FI", "encrypted_meta": "opaque-cli"},
        },
    })

    updated = asyncio.run(
        auth_common.set_session_security_country(cache, "user-1", "cli-token", "US")
    )

    assert updated is True
    assert cache.values["user_tokens:user-1"][browser_hash] == {
        "security_country_code": "DE",
        "encrypted_meta": "opaque-browser",
    }
    assert cache.values["user_tokens:user-1"][cli_hash] == {
        "security_country_code": "US",
        "encrypted_meta": "opaque-cli",
    }


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
def test_refresh_rotation_preserves_session_security_metadata():
    old_hash = token_hash("old-token")
    new_hash = token_hash("new-token")
    cache = FakeCache({
        "user_tokens:user-1": {
            old_hash: {
                "created_at": 123,
                "stay_logged_in": True,
                "security_country_code": "FI",
                "encrypted_meta": "opaque",
            },
        },
    })

    user_data = {"stay_logged_in": False}
    asyncio.run(
        auth_common.preserve_rotated_session_metadata(
            cache,
            user_id="user-1",
            old_refresh_token="old-token",
            new_refresh_token="new-token",
            user_data=user_data,
        )
    )

    assert old_hash not in cache.values["user_tokens:user-1"]
    assert cache.values["user_tokens:user-1"][new_hash]["security_country_code"] == "FI"
    assert cache.values["user_tokens:user-1"][new_hash]["encrypted_meta"] == "opaque"
    assert user_data["stay_logged_in"] is True


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth
def test_device_identity_is_independent_from_country(monkeypatch):
    countries = iter(("DE", "FI"))

    def geo(_ip):
        return {
            "country_code": next(countries),
            "region": None,
            "city": None,
            "latitude": None,
            "longitude": None,
        }

    monkeypatch.setattr(device_fingerprint, "get_geo_data_from_ip", geo)

    first = device_fingerprint.generate_device_fingerprint_hash(FakeRequest(), "user-1", "tab-1")
    second = device_fingerprint.generate_device_fingerprint_hash(FakeRequest(), "user-1", "tab-1")

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[3] == "DE"
    assert second[3] == "FI"


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth
def test_legacy_device_hash_remains_available_for_migration():
    expected = hashlib.sha256("Linux:FI:user-1".encode()).hexdigest()

    assert (
        device_fingerprint.generate_legacy_device_fingerprint_hash(
            "Linux", "FI", "user-1"
        )
        == expected
    )
