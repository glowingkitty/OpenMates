"""
Regression tests for self-hosted signup mode requirements.

These tests pin the public signup contract for self-hosted instances: signup is
never accidentally open, and invite-code/domain requirements are driven by the
explicit self-host signup mode selected during install.
"""

import pytest

from backend.core.api.app.utils.invite_code import get_signup_requirements, is_email_domain_allowed


class DummyCache:
    async def get(self, _key):
        return None

    async def set(self, _key, _value, ttl=None):
        return True


class DummyDirectus:
    async def get_completed_signups_count(self):
        return 0


@pytest.mark.asyncio
async def test_self_host_defaults_to_invite_only(monkeypatch):
    monkeypatch.setenv("PRODUCTION_URL", "http://localhost:5173")
    monkeypatch.delenv("SELF_HOST_SIGNUP_MODE", raising=False)
    monkeypatch.delenv("SELF_HOST_SIGNUP_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("SIGNUP_TEST_EMAIL_DOMAINS", raising=False)

    require_invite, require_domain, domains = await get_signup_requirements(DummyDirectus(), DummyCache())

    assert require_invite is True
    assert require_domain is False
    assert domains is None


@pytest.mark.asyncio
async def test_self_host_domain_allowlist_requires_domain_only(monkeypatch):
    monkeypatch.setenv("PRODUCTION_URL", "http://localhost:5173")
    monkeypatch.setenv("SELF_HOST_SIGNUP_MODE", "domain_allowlist")
    monkeypatch.setenv("SELF_HOST_SIGNUP_ALLOWED_DOMAINS", "team.test, friends.test")
    monkeypatch.delenv("SIGNUP_TEST_EMAIL_DOMAINS", raising=False)

    require_invite, require_domain, domains = await get_signup_requirements(DummyDirectus(), DummyCache())

    assert require_invite is False
    assert require_domain is True
    assert domains == ["team.test", "friends.test"]


@pytest.mark.asyncio
async def test_self_host_invite_and_domain_requires_both(monkeypatch):
    monkeypatch.setenv("PRODUCTION_URL", "http://localhost:5173")
    monkeypatch.setenv("SELF_HOST_SIGNUP_MODE", "invite_and_domain")
    monkeypatch.setenv("SELF_HOST_SIGNUP_ALLOWED_DOMAINS", "team.test")
    monkeypatch.delenv("SIGNUP_TEST_EMAIL_DOMAINS", raising=False)

    require_invite, require_domain, domains = await get_signup_requirements(DummyDirectus(), DummyCache())

    assert require_invite is True
    assert require_domain is True
    assert domains == ["team.test"]


@pytest.mark.asyncio
async def test_self_host_domain_mode_without_domains_falls_back_to_invite(monkeypatch):
    monkeypatch.setenv("PRODUCTION_URL", "http://localhost:5173")
    monkeypatch.setenv("SELF_HOST_SIGNUP_MODE", "domain_allowlist")
    monkeypatch.delenv("SELF_HOST_SIGNUP_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("SIGNUP_TEST_EMAIL_DOMAINS", raising=False)

    require_invite, require_domain, domains = await get_signup_requirements(DummyDirectus(), DummyCache())

    assert require_invite is True
    assert require_domain is False
    assert domains is None


def test_email_domain_allowlist_uses_exact_domains():
    allowed, domain = is_email_domain_allowed("person@team.test", ["team.test"])

    assert allowed is True
    assert domain == "team.test"


def test_email_domain_allowlist_rejects_subdomain_and_invalid_email():
    subdomain_allowed, subdomain = is_email_domain_allowed("person@sub.team.test", ["team.test"])
    invalid_allowed, invalid_domain = is_email_domain_allowed("not-an-email", ["team.test"])

    assert subdomain_allowed is False
    assert subdomain == "sub.team.test"
    assert invalid_allowed is False
    assert invalid_domain is None
