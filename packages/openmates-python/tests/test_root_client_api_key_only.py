"""Python OpenMatesClient requires an explicit API key at construction (npm parity)."""
# contract-test-file: tooling
import pytest

import openmates
from openmates import (
    OpenMates,
    OpenMatesApiKeyRequiredError,
    OpenMatesClient,
    OpenMatesConfigError,
    SDK_API_KEY_REQUIRED_CODE,
)


# contract-test: direct surface=sdks.pip assertions=sdk.auth.api-key-only
@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_missing_api_key_is_typed_construction_error_without_env_fallback(api_key, monkeypatch, tmp_path):
    # The strict client never reads the environment, unlike OpenMates' 0.x convenience.
    monkeypatch.setenv("OPENMATES_API_KEY", "sk-api-ambient")
    for build in (OpenMatesClient, OpenMatesClient.load):
        with pytest.raises(OpenMatesApiKeyRequiredError) as raised:
            build(api_key, device_id_path=tmp_path / "device-id")
        assert isinstance(raised.value, OpenMatesConfigError)
        assert raised.value.code == SDK_API_KEY_REQUIRED_CODE == "OPENMATES_SDK_API_KEY_REQUIRED"
        assert "Settings → Developers" in str(raised.value)
    assert not (tmp_path / "device-id").exists(), "refused before any device identity IO"


@pytest.mark.parametrize("legacy", [{"session": {}}, {"load_stored_session": True}, {"load_stored_session": False}])
def test_legacy_cli_session_options_are_refused(legacy):
    with pytest.raises(OpenMatesApiKeyRequiredError):
        OpenMatesClient("sk-api-x", device_id="synthetic-device", **legacy)
    with pytest.raises(OpenMatesConfigError):
        OpenMatesClient("sk-api-x", device_id="synthetic-device", unknown=True)


def test_explicit_key_builds_an_account_client(monkeypatch):
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)
    client = OpenMatesClient("sk-api-explicit", "https://api.example.invalid/", device_id="synthetic-device")
    assert isinstance(client, OpenMates)
    assert client._api_key == "sk-api-explicit"
    assert client._api_url == "https://api.example.invalid"
    assert "OpenMatesClient" in openmates.__all__ and "OpenMatesApiKeyRequiredError" in openmates.__all__
