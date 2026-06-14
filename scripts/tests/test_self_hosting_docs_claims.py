#!/usr/bin/env python3
"""
Regression tests for self-hosting documentation claims.

These checks keep operational docs tied to the source/config contracts they
describe without running server-hardening commands on the host.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def doc_assert(claim_id: str) -> None:
    assert claim_id


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_self_hosting_readme_links_core_guides() -> None:
    doc_assert("self-hosting-readme-links-core-guides")
    text = read("docs/self-hosting/README.md")

    assert "[Setup & Installation](setup.md)" in text
    assert "[Server Hardening](server-hardening.md)" in text
    assert "[Proton Mail Bridge](proton-bridge.md)" in text


def test_proton_bridge_docs_match_provider_contract() -> None:
    doc_assert("self-hosting-proton-bridge-docs-provider-contract")
    doc = read("docs/self-hosting/proton-bridge.md")
    provider = read("backend/shared/providers/protonmail/protonmail_bridge.py")
    apps_route = read("backend/core/api/app/routes/apps.py")
    mail_skill = read("backend/apps/mail/skills/search_skill.py")

    expected_env_keys = [
        "SECRET__PROTONMAIL__ENABLED",
        "SECRET__PROTONMAIL__BRIDGE_HOST",
        "SECRET__PROTONMAIL__BRIDGE_IMAP_PORT",
        "SECRET__PROTONMAIL__BRIDGE_USERNAME",
        "SECRET__PROTONMAIL__BRIDGE_PASSWORD",
        "SECRET__PROTONMAIL__MAILBOX",
        "SECRET__PROTONMAIL__ALLOWED_OPENMATES_EMAIL",
    ]
    for key in expected_env_keys:
        assert key in doc
        assert key in provider or key in apps_route

    assert "is_user_allowed_for_protonmail" in provider
    assert "_is_protonmail_user_allowed" in apps_route
    assert "search_protonmail_messages" in mail_skill
    assert "check_protonmail_bridge_health" in provider


def test_server_hardening_docs_cover_six_layers_and_verification_commands() -> None:
    doc_assert("self-hosting-server-hardening-covers-six-layers")
    text = read("docs/self-hosting/server-hardening.md")

    for layer in ["Layer A", "Layer B", "Layer C", "Layer D", "Layer E", "Layer F"]:
        assert f"## {layer}" in text
    for command_anchor in [
        "PermitRootLogin no",
        "PasswordAuthentication no",
        "pam_google_authenticator.so",
        "AuthenticationMethods publickey,keyboard-interactive",
        "sudo ufw default deny incoming",
        "unattended-upgrades",
    ]:
        assert command_anchor in text
