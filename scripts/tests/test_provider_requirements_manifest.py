#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the provider requirements manifest used by self-host update preflight.

These tests intentionally read real backend/providers/*.yml files. They prevent
the CLI from falling back to .env.example scraping or stale hardcoded key lists
when warning operators about newly required provider credentials.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

manifest_module = importlib.import_module("provider_requirements_manifest")
contract_audits = importlib.import_module("contract_audits")


def _providers_by_id() -> dict[str, dict]:
    manifest = manifest_module.build_manifest()
    return {provider["provider_id"]: provider for provider in manifest["providers"]}


def test_every_provider_declares_auth_requirements() -> None:
    manifest = manifest_module.build_manifest()

    assert manifest_module.missing_provider_metadata(manifest) == []


def test_manifest_contains_expected_provider_key_metadata() -> None:
    providers = _providers_by_id()

    brave = providers["brave"]
    assert brave["requirement_level"] == "required"
    assert brave["required_keys"][0]["env_key"] == "SECRET__BRAVE__API_KEY"
    assert brave["required_keys"][0]["vault_path"] == "kv/data/providers/brave"
    assert brave["required_keys"][0]["setup_url"].startswith("https://")

    open_meteo = providers["open_meteo"]
    assert open_meteo["requirement_level"] == "no_api_key"
    assert open_meteo["required_keys"] == []


def test_manifest_does_not_contain_secret_values() -> None:
    manifest = manifest_module.build_manifest()
    rendered = repr(manifest).lower()

    assert "sk-" not in rendered
    assert "placeholder" not in rendered
    assert "your_key" not in rendered
    assert "api key value" not in rendered


def test_contract_audit_enforces_provider_requirements_metadata() -> None:
    findings = contract_audits.audit_provider_requirements_contract()

    assert findings == []
