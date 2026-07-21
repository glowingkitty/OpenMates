#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the self-host provider requirements manifest from backend provider YAML.

The manifest is metadata-only: it records env key names, Vault locations, and
setup/documentation URLs, but never secret values. Release/update preflight code
can diff two manifests without scraping .env.example or provider comments.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_DIR = REPO_ROOT / "backend" / "providers"
SECRET_FIELD_NAMES = {"value", "secret", "api_key", "token", "password", "private_key"}


def _read_provider(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping in {path}")
    return raw


def _normalize_key(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Provider key entries must be mappings")
    entry = {key: value for key, value in raw.items() if value is not None}
    env_key = entry.get("env_key")
    vault_path = entry.get("vault_path")
    vault_key = entry.get("vault_key")
    if not isinstance(env_key, str) or not env_key.strip():
        raise ValueError("Provider key entries require env_key")
    if vault_path is not None and (not isinstance(vault_path, str) or not vault_path.strip()):
        raise ValueError(f"{env_key} has invalid vault_path")
    if vault_key is not None and (not isinstance(vault_key, str) or not vault_key.strip()):
        raise ValueError(f"{env_key} has invalid vault_key")
    for field in SECRET_FIELD_NAMES:
        if field in entry:
            raise ValueError(f"{env_key} must not include secret field {field}")
    return entry


def provider_requirement(path: Path) -> dict[str, Any]:
    provider = _read_provider(path)
    provider_id = str(provider.get("provider_id") or path.stem).strip()
    required_keys = [_normalize_key(item) for item in provider.get("required_keys") or []]
    optional_keys = [_normalize_key(item) for item in provider.get("optional_keys") or []]
    no_api_key = provider.get("no_api_key") is True
    if no_api_key and (required_keys or optional_keys):
        raise ValueError(f"{provider_id} cannot combine no_api_key with key requirements")
    if required_keys:
        requirement_level = "required"
    elif optional_keys:
        requirement_level = "optional"
    elif no_api_key:
        requirement_level = "no_api_key"
    else:
        requirement_level = "missing_metadata"
    return {
        "provider_id": provider_id,
        "name": provider.get("name") or provider_id,
        "requirement_level": requirement_level,
        "required_keys": required_keys,
        "optional_keys": optional_keys,
        "no_api_key": no_api_key,
        "docs_url": provider.get("docs_url"),
        "source": str(path.relative_to(REPO_ROOT)),
    }


def build_manifest(providers_dir: Path = PROVIDERS_DIR) -> dict[str, Any]:
    providers = [provider_requirement(path) for path in sorted(providers_dir.glob("*.yml"))]
    digest_source = yaml.safe_dump(providers, sort_keys=True, allow_unicode=False)
    return {
        "schema_version": 1,
        "digest": hashlib.sha256(digest_source.encode("utf-8")).hexdigest(),
        "providers": providers,
    }


def missing_provider_metadata(manifest: dict[str, Any]) -> list[str]:
    return [
        str(provider["provider_id"])
        for provider in manifest.get("providers") or []
        if provider.get("requirement_level") == "missing_metadata"
    ]
