#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Static URL checks for provider requirement setup guidance.

Live reachability/relevance checks are recorded separately with Firecrawl. This
test keeps obviously invalid, non-HTTPS, or secret-looking setup/docs URLs out
of committed provider metadata before those live checks run.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

manifest_module = importlib.import_module("provider_requirements_manifest")


def _urls_for_provider(provider: dict) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    if provider.get("docs_url"):
        urls.append(("docs_url", str(provider["docs_url"])))
    for section in ("required_keys", "optional_keys"):
        for index, key in enumerate(provider.get(section) or []):
            for field in ("setup_url", "docs_url"):
                if key.get(field):
                    urls.append((f"{section}[{index}].{field}", str(key[field])))
    return urls


def test_provider_setup_and_docs_urls_are_https() -> None:
    manifest = manifest_module.build_manifest()
    failures: list[str] = []

    for provider in manifest["providers"]:
        for field, url in _urls_for_provider(provider):
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc or any(char.isspace() for char in url):
                failures.append(f"{provider['provider_id']} {field}: {url}")

    assert failures == []


def test_provider_setup_urls_do_not_embed_credentials() -> None:
    manifest = manifest_module.build_manifest()
    failures: list[str] = []

    for provider in manifest["providers"]:
        for field, url in _urls_for_provider(provider):
            parsed = urlparse(url)
            if parsed.username or parsed.password or "api_key=" in parsed.query.lower() or "token=" in parsed.query.lower():
                failures.append(f"{provider['provider_id']} {field}: {url}")

    assert failures == []
