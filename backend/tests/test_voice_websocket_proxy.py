"""The only speech egress override is the isolated runner's fixed CONNECT tunnel."""

import pytest

from backend.shared.providers.voice_websocket_proxy import isolated_voice_websocket_proxy

PROOF_ENV = {
    "CI": "true",
    "OPENMATES_CI_ISOLATED": "1",
    "OPENMATES_CI_REAL_INFERENCE": "1",
    "OPENMATES_CI_REAL_WEB_VOICE": "1",
    "SERVER_ENVIRONMENT": "development",
}


@pytest.fixture
def proof_env(monkeypatch):
    for key, value in PROOF_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENMATES_CI_AI_FIXTURES", raising=False)


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary
def test_proof_has_one_fixed_proxy_and_ignores_operator_proxy_values(proof_env, monkeypatch):
    monkeypatch.setenv("WSS_PROXY", "https://other.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "https://other.invalid")
    assert isolated_voice_websocket_proxy() == "http://runner-gateway:3128"
    monkeypatch.delenv("OPENMATES_CI_REAL_WEB_VOICE")
    assert isolated_voice_websocket_proxy() is None


@pytest.mark.parametrize(("key", "value"), [
    ("CI", "false"),
    ("OPENMATES_CI_ISOLATED", "0"),
    ("OPENMATES_CI_REAL_INFERENCE", "0"),
    ("OPENMATES_CI_AI_FIXTURES", "1"),
    ("SERVER_ENVIRONMENT", "production"),
])
# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary
def test_invalid_lane_cannot_fall_back_to_direct_speech_network(proof_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="isolated real-inference"):
        isolated_voice_websocket_proxy()
