"""Shared fixtures for instance app package tests (no pytest collection here).

Builds a package root in the layout written by the host CLI
(docs/architecture/apps/instance-app-packages.md): ``registry.json`` plus
``packages/<id>/<version>/{manifest.yml, install.json, files/...}``. The example
provider stands for an operator's own website events API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from backend.shared.app_packages import loader

PACKAGE_ID = "org.example.website-events"
VERSION = "1.0.0"
PROVIDER_ID = "example_site_events"
PROVIDER_NAME = "Example site events"


def provider_entry(**overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "app": "events",
        "skill": "search",
        "contract": "events.search@1",
        "id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "runtime": "executable",
        "entrypoint": "bin/provider",
        "secrets": ["api_key"],
        "skill_hint": "Use for events published on the operator's own website.",
    }
    entry.update(overrides)
    return entry


def manifest(package_id: str = PACKAGE_ID, version: str = VERSION,
             providers: Optional[List[Dict[str, Any]]] = None, **overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "format": "openmates-app-package",
        "format_version": 1,
        "id": package_id,
        "version": version,
        "name": "Website events",
        "description": "Events from the operator's own website.",
        "contributes": {"providers": providers if providers is not None else [provider_entry()]},
    }
    data.update(overrides)
    return data


def write_package(root: Path, manifest_data: Dict[str, Any], *, package_id: str = PACKAGE_ID,
                  version: str = VERSION, files: Optional[Dict[str, str]] = None) -> str:
    """Write one installed version and return its archive digest placeholder."""
    version_dir = root / "packages" / package_id / version
    (version_dir / "files").mkdir(parents=True, exist_ok=True)
    manifest_text = yaml.safe_dump(manifest_data, sort_keys=False)
    (version_dir / "manifest.yml").write_text(manifest_text, encoding="utf-8")
    (version_dir / "files" / "manifest.yml").write_text(manifest_text, encoding="utf-8")
    digests = {"manifest.yml": hashlib.sha256(manifest_text.encode()).hexdigest()}
    for rel, content in (files or {}).items():
        path = version_dir / "files" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        digests[rel] = hashlib.sha256(content.encode()).hexdigest()
    sha = hashlib.sha256(f"{package_id}@{version}".encode()).hexdigest()
    (version_dir / "install.json").write_text(json.dumps({
        "package_id": package_id, "version": version, "archive_sha256": sha, "file_digests": digests,
    }), encoding="utf-8")
    return sha


def write_registry(root: Path, active: Dict[str, Dict[str, str]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "registry.json").write_text(json.dumps({
        "format": 1, "revision": 1, "active": active,
        "installed": {pid: [entry["version"]] for pid, entry in active.items()},
    }), encoding="utf-8")


def install_example(root: Path, manifest_data: Optional[Dict[str, Any]] = None) -> None:
    sha = write_package(root, manifest_data or manifest())
    write_registry(root, {PACKAGE_ID: {"version": VERSION, "sha256": sha}})


def enable(monkeypatch: Any, root: Path) -> None:
    """Point the process-wide loader at ``root`` with app packages enabled."""
    monkeypatch.setenv(loader.ENABLED_ENV, "true")
    monkeypatch.setenv(loader.MOUNT_ENV, str(root))
    loader.reset_installed_packages_cache()


class FakeSecretsManager:
    """Vault stand-in: ``values`` maps (path, key) to a secret value."""

    vault_token = "placeholder-token"
    vault_url = "http://vault.invalid"

    def __init__(self, values: Optional[Dict[tuple, str]] = None) -> None:
        self.values = values or {}
        self.calls: List[tuple] = []

    async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True) -> Optional[str]:
        self.calls.append((secret_path, secret_key))
        return self.values.get((secret_path, secret_key))


def configured_secrets() -> FakeSecretsManager:
    return FakeSecretsManager({(f"kv/data/providers/{PROVIDER_ID}", "api_key"): "placeholder-value"})
