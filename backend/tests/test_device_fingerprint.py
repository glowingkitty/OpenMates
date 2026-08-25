"""
backend/tests/test_device_fingerprint.py

Security-focused tests for client IP extraction. Forwarding headers are trusted
only when the direct peer is a local reverse proxy, preventing identity spoofing.
"""

from backend.core.api.app.utils.device_fingerprint import _extract_client_ip


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_public_peer_cannot_spoof_forwarded_ip() -> None:
    assert _extract_client_ip(
        {"x-real-ip": "1.1.1.1", "x-forwarded-for": "9.9.9.9"},
        "8.8.8.8",
    ) == "8.8.8.8"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_loopback_proxy_can_forward_real_client_ip() -> None:
    assert _extract_client_ip(
        {"x-real-ip": "1.1.1.1", "x-forwarded-for": "9.9.9.9"},
        "127.0.0.1",
    ) == "1.1.1.1"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_private_proxy_uses_first_forwarded_ip_when_real_ip_is_invalid() -> None:
    assert _extract_client_ip(
        {"x-real-ip": "invalid", "x-forwarded-for": "9.9.9.9, 10.0.0.3"},
        "10.0.0.2",
    ) == "9.9.9.9"
