"""Provider ids an installed app package may never claim.

Installed provider secrets resolve from the shared provider namespace
(Vault ``kv/data/providers/<provider_id>`` and ``SECRET__<PROVIDER>__<KEY>``),
and provider availability is keyed by id. A package whose provider id equals
any built-in provider id would therefore receive the server's own provider keys
and could mark built-in providers available. The loader rejects such packages
before any secret is resolved (feature.instance-app-packages: operator-secrets).

The global set is derived at load time from the source tree, so new built-in
providers are covered without a hand-maintained list:
- provider ids and names in every built-in ``app.yml``;
- ``provider_id`` values and file names of provider configs (``backend/providers``);
- provider module names under ``backend/shared/providers``;
- Vault provider paths (``kv/data/providers/<id>``) and ``SECRET__<ID>__`` prefixes
  referenced by backend code, compose files and the repository ``.env.example``.

Per-skill reserved ids (selector aliases such as ``auto``) come from the
contract registry (``contracts.reserved_provider_ids``).
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_VAULT_PATH_RE = re.compile(r"kv/data/providers/([A-Za-z0-9_\-]+)")
_SECRET_ENV_RE = re.compile(r"SECRET__([A-Z0-9_]+?)__")
# libyaml keeps the one-time scan of ~90 config files fast when available.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_SKIPPED_DIRS = frozenset({"tests", "node_modules", "__pycache__", "venv"})


def normalize_provider_id(value: Any) -> str:
    """Normalize a provider id or display name to the package provider id form."""
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


def _provider_entries_ids(providers: Iterable[Any]) -> set[str]:
    ids: set[str] = set()
    for provider in providers or []:
        if isinstance(provider, str):
            ids.add(normalize_provider_id(provider))
        elif isinstance(provider, dict):
            ids.update(normalize_provider_id(provider[key]) for key in ("id", "name") if provider.get(key))
    return ids


def _read_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.load(handle, Loader=_YAML_LOADER)
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[AppPackages] Cannot read %s for reserved provider ids: %s", path, exc)
        return None


def _app_provider_ids(apps_dir: Path) -> set[str]:
    ids: set[str] = set()
    for app_yml in sorted(apps_dir.glob("*/app.yml")):
        config = _read_yaml(app_yml)
        skills = config.get("skills") if isinstance(config, dict) else None
        for skill in skills or []:
            if isinstance(skill, dict):
                ids |= _provider_entries_ids(skill.get("providers") or [])
    return ids


def _provider_config_ids(backend_root: Path) -> set[str]:
    ids: set[str] = set()
    for config_path in sorted((backend_root / "providers").glob("*.yml")):
        ids.add(normalize_provider_id(config_path.stem))
        config = _read_yaml(config_path)
        if isinstance(config, dict) and config.get("provider_id"):
            ids.add(normalize_provider_id(config["provider_id"]))
    shared_providers = backend_root / "shared" / "providers"
    if shared_providers.is_dir():
        ids.update(
            normalize_provider_id(entry.stem)
            for entry in shared_providers.iterdir()
            if not entry.name.startswith(("_", ".")) and (entry.is_dir() or entry.suffix == ".py")
        )
    return ids


def _scanned_files(backend_root: Path) -> Iterable[Path]:
    for directory, subdirs, files in os.walk(backend_root):
        subdirs[:] = [name for name in subdirs if name not in _SKIPPED_DIRS and not name.startswith(".")]
        for name in files:
            if name.endswith(".py"):
                yield Path(directory) / name
    yield from sorted((backend_root / "core").glob("docker-compose*.yml"))
    env_example = backend_root.parent / ".env.example"
    if env_example.is_file():
        yield env_example


def _secret_namespace_ids(backend_root: Path) -> set[str]:
    ids: set[str] = set()
    for path in _scanned_files(backend_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        ids.update(normalize_provider_id(match) for match in _VAULT_PATH_RE.findall(text))
        ids.update(normalize_provider_id(match) for match in _SECRET_ENV_RE.findall(text))
    return ids


@lru_cache(maxsize=4)
def builtin_provider_namespace(apps_dir: Path, backend_root: Path = BACKEND_ROOT) -> frozenset[str]:
    """Every provider id built-in code may use for availability or secrets."""
    ids = _app_provider_ids(apps_dir) | _provider_config_ids(backend_root) | _secret_namespace_ids(backend_root)
    ids.discard("")
    return frozenset(ids)
