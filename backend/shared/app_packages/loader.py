"""Load operator-installed app package providers from the read-only package root.

Instance app packages (docs/architecture/apps/instance-app-packages.md) are
written only by the host CLI and mounted read-only at ``/app-packages``. This
module reads ``registry.json`` and the active versions' manifests once per
process when ``OPENMATES_APP_PACKAGES_ENABLED=true`` and exposes the validated
provider contributions.

Trust rules:
- Flag off: nothing is read; every lookup is empty.
- Missing or invalid ``registry.json``: an error is logged and nothing loads.
- An invalid package (manifest, install record, target skill, contract or id
  collision) is rejected as a whole with an error log; valid packages still load.
- A target skill accepts the contract named by its ``provider_contract``, or the
  generic ``skill.requests@1`` while it is paused without any provider
  (``generic_contract.accepts_generic_contract``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from backend.shared.app_packages.contracts import reserved_provider_ids
from backend.shared.app_packages.generic_contract import GENERIC_CONTRACTS, accepts_generic_contract
from backend.shared.app_packages.reserved_ids import builtin_provider_namespace

logger = logging.getLogger(__name__)

ENABLED_ENV = "OPENMATES_APP_PACKAGES_ENABLED"
MOUNT_ENV = "OPENMATES_APP_PACKAGES_MOUNT"
DEFAULT_MOUNT = "/app-packages"
BUILTIN_APPS_DIR = Path(__file__).resolve().parents[2] / "apps"

MANIFEST_FORMAT = "openmates-app-package"
SUPPORTED_FORMAT_VERSION = 1
REGISTRY_FORMAT = 1
SUPPORTED_RUNTIME = "executable"
MAX_PACKAGE_ID_LENGTH = 64
MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 1000
MAX_SKILL_HINT_LENGTH = 1000
MAX_ENTRYPOINT_LENGTH = 255

PACKAGE_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_-]+)+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
PROVIDER_ID_RE = re.compile(r"^[a-z0-9_]{2,40}$")
SECRET_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
CONTRACT_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+@[1-9][0-9]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REGION_CODE_RE = re.compile(r"^[A-Z]{2}$")
MAX_PROVIDER_REGIONS = 60
PROVIDER_KEYS = frozenset({
    "app", "skill", "contract", "id", "name", "runtime", "entrypoint", "secrets", "optional_secrets", "skill_hint",
    "regions",
})
MANIFEST_KEYS = frozenset({"format", "format_version", "id", "version", "name", "description", "contributes"})


@dataclass(frozen=True)
class InstalledProvider:
    """One validated provider contribution of an active package version."""

    package_id: str
    package_version: str
    archive_sha256: str
    app_id: str
    skill_id: str
    contract: str
    provider_id: str
    name: str
    entrypoint: str
    secrets: Tuple[str, ...]
    skill_hint: Optional[str]
    # Passed only when configured; never affect availability (for example a proxy URL).
    optional_secrets: Tuple[str, ...] = ()
    # ISO 3166-1 alpha-2 codes the provider covers; empty means worldwide.
    regions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class InstalledPackages:
    """Immutable view of every validated, active provider contribution."""

    providers: Tuple[InstalledProvider, ...] = ()

    def for_skill(self, app_id: str, skill_id: str) -> List[InstalledProvider]:
        return [p for p in self.providers if p.app_id == app_id and p.skill_id == skill_id]

    def for_app(self, app_id: str) -> List[InstalledProvider]:
        return [p for p in self.providers if p.app_id == app_id]

    def get(self, app_id: str, skill_id: str, provider_id: str) -> Optional[InstalledProvider]:
        return next((p for p in self.for_skill(app_id, skill_id) if p.provider_id == provider_id), None)


class InvalidPackage(ValueError):
    """Raised while validating one package; the package is skipped."""


def app_packages_enabled() -> bool:
    """Flag state; always off on a hosted production server, where packaged providers are not billed."""
    if os.getenv(ENABLED_ENV, "").strip().lower() != "true":
        return False
    hosted_production = (
        os.getenv("OPENMATES_DEPLOYMENT_MODE", "") == "official_cloud"
        and os.getenv("SERVER_ENVIRONMENT", "") != "development"
    )
    return not hosted_production


def package_mount() -> Path:
    return Path(os.getenv(MOUNT_ENV, DEFAULT_MOUNT))


_cache_lock = threading.Lock()
_cache: Optional[InstalledPackages] = None
EMPTY = InstalledPackages()


def get_installed_packages() -> InstalledPackages:
    """Return the process-wide installed providers (loaded once, empty when disabled)."""
    global _cache
    if not app_packages_enabled():
        return EMPTY
    with _cache_lock:
        if _cache is None:
            _cache = load_installed_packages(package_mount())
        return _cache


def reset_installed_packages_cache() -> None:
    """Forget the loaded registry (tests; a restart is the production reload path)."""
    global _cache
    with _cache_lock:
        _cache = None


def get_installed_providers(app_id: str, skill_id: str) -> List[InstalledProvider]:
    return get_installed_packages().for_skill(app_id, skill_id)


def get_installed_provider(app_id: str, skill_id: str, provider_id: str) -> Optional[InstalledProvider]:
    return get_installed_packages().get(app_id, skill_id, provider_id)


def is_installed_provider(app_id: str, skill_id: str, provider_id: Any) -> bool:
    """True only when the server registry has an active contribution with this id."""
    return isinstance(provider_id, str) and get_installed_provider(app_id, skill_id, provider_id) is not None


# --------------------------------------------------------------------------
# Loading and validation
# --------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidPackage(message)


def _optional_text(value: Any, field: str, limit: int) -> Optional[str]:
    if value is None:
        return None
    _require(isinstance(value, str) and len(value.strip()) <= limit, f"{field} must be a string of at most {limit} chars")
    return value.strip() or None


def _safe_entrypoint(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_ENTRYPOINT_LENGTH:
        return False
    if value.startswith("/") or "\\" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


class _BuiltinTargets:
    """Read built-in app.yml files to validate contribution targets."""

    def __init__(self, apps_dir: Path) -> None:
        self._apps_dir = apps_dir
        self._skills: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._reserved_by_contract: Dict[str, frozenset[str]] = {}

    def global_provider_ids(self) -> frozenset[str]:
        """Built-in provider ids across all apps, provider configs and secret paths."""
        return builtin_provider_namespace(self._apps_dir.resolve())

    def reserved_for_contract(self, contract: str) -> frozenset[str]:
        """Selector values the target skill interprets itself (for example ``auto``)."""
        if contract not in self._reserved_by_contract:
            try:
                self._reserved_by_contract[contract] = reserved_provider_ids(contract)
            except (ImportError, AttributeError) as exc:
                raise InvalidPackage(f"reserved provider ids for {contract} are unavailable: {exc}") from exc
        return self._reserved_by_contract[contract]

    def skill(self, app_id: str, skill_id: str) -> Optional[Dict[str, Any]]:
        if app_id not in self._skills:
            self._skills[app_id] = self._load(app_id)
        return self._skills[app_id].get(skill_id)

    def _load(self, app_id: str) -> Dict[str, Dict[str, Any]]:
        if not re.fullmatch(r"[a-z0-9_]+", app_id):
            return {}
        path = self._apps_dir / app_id / "app.yml"
        try:
            with path.open("r", encoding="utf-8") as handle:
                config = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.error("[AppPackages] Cannot read built-in app '%s' for target validation: %s", app_id, exc)
            return {}
        skills = config.get("skills") if isinstance(config, dict) else None
        return {
            str(skill.get("id")): skill
            for skill in skills or []
            if isinstance(skill, dict) and skill.get("id") and skill.get("class_path")
        }


def _builtin_provider_ids(skill: Dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for provider in skill.get("providers") or []:
        if isinstance(provider, str):
            ids.add(provider.strip().lower())
        elif isinstance(provider, dict):
            ids.update(str(provider.get(key)).strip().lower() for key in ("id", "name") if provider.get(key))
    return ids


def _secret_names(value: Any, field: str) -> List[str]:
    names = value or []
    _require(isinstance(names, list) and all(isinstance(s, str) and SECRET_NAME_RE.match(s) for s in names),
             f"provider {field} must be a list of lowercase names")
    _require(len(set(names)) == len(names), f"provider {field} must be unique")
    return names


def _regions(value: Any) -> List[str]:
    if value is None:
        return []
    _require(isinstance(value, list) and 0 < len(value) <= MAX_PROVIDER_REGIONS
             and all(isinstance(code, str) and REGION_CODE_RE.match(code) for code in value),
             f"provider regions must be a list of 1-{MAX_PROVIDER_REGIONS} ISO 3166-1 alpha-2 codes (e.g. DE)")
    _require(len(set(value)) == len(value), "provider regions must be unique")
    return value


def _validate_provider(raw: Any, package: Dict[str, str], targets: _BuiltinTargets) -> InstalledProvider:
    _require(isinstance(raw, dict), "provider contribution must be a mapping")
    unknown = set(raw) - PROVIDER_KEYS
    _require(not unknown, f"unsupported provider fields: {sorted(unknown)}")
    app_id, skill_id, contract = raw.get("app"), raw.get("skill"), raw.get("contract")
    provider_id, name = raw.get("id"), raw.get("name")
    _require(isinstance(app_id, str) and isinstance(skill_id, str), "provider app and skill are required")
    _require(isinstance(contract, str) and bool(CONTRACT_RE.match(contract)), "provider contract is invalid")
    _require(isinstance(provider_id, str) and bool(PROVIDER_ID_RE.match(provider_id)), "provider id is invalid")
    _require(isinstance(name, str) and 0 < len(name.strip()) <= MAX_NAME_LENGTH, "provider name is invalid")
    _require(raw.get("runtime") == SUPPORTED_RUNTIME, "provider runtime must be 'executable'")
    _require(_safe_entrypoint(raw.get("entrypoint")), "provider entrypoint must be a safe relative path")
    target = targets.skill(app_id, skill_id)
    _require(target is not None, f"unknown target skill {app_id}.{skill_id}")
    # A skill accepts the contract it declares, or the generic contract while it is
    # paused for lack of any provider (provider_required, no providers, no contract).
    accepts = accepts_generic_contract(target) if contract in GENERIC_CONTRACTS else (
        target.get("provider_contract") == contract)
    _require(accepts, f"{app_id}.{skill_id} does not accept contract {contract}")
    # Secrets resolve from the shared provider namespace, so an id used by any
    # built-in provider (any app, provider config or secret path) is refused.
    _require(provider_id not in _builtin_provider_ids(target) and provider_id not in targets.global_provider_ids(),
             f"provider id '{provider_id}' collides with a built-in provider")
    _require(provider_id not in targets.reserved_for_contract(contract),
             f"provider id '{provider_id}' is reserved by {app_id}.{skill_id}")
    secrets = _secret_names(raw.get("secrets"), "secrets")
    optional_secrets = _secret_names(raw.get("optional_secrets"), "optional_secrets")
    overlap = sorted(set(secrets) & set(optional_secrets))
    _require(not overlap, f"provider secrets and optional_secrets overlap: {overlap}")
    return InstalledProvider(
        package_id=package["id"], package_version=package["version"], archive_sha256=package["sha256"],
        app_id=app_id, skill_id=skill_id, contract=contract, provider_id=provider_id, name=name.strip(),
        entrypoint=raw["entrypoint"], secrets=tuple(secrets),
        skill_hint=_optional_text(raw.get("skill_hint"), "skill_hint", MAX_SKILL_HINT_LENGTH),
        optional_secrets=tuple(optional_secrets),
        regions=tuple(_regions(raw.get("regions"))),
    )


def _load_package(root: Path, package_id: str, active: Any, targets: _BuiltinTargets) -> List[InstalledProvider]:
    _require(isinstance(package_id, str) and len(package_id) <= MAX_PACKAGE_ID_LENGTH
             and bool(PACKAGE_ID_RE.match(package_id)), "package id is invalid")
    _require(isinstance(active, dict), "active entry must be a mapping")
    version, sha = active.get("version"), active.get("sha256")
    _require(isinstance(version, str) and bool(VERSION_RE.match(version)), "active version is invalid")
    _require(isinstance(sha, str) and bool(SHA256_RE.match(sha)), "active sha256 is invalid")
    version_dir = root / "packages" / package_id / version
    try:
        install = _read_json(version_dir / "install.json")
        # The runner executes from files/, whose digests install.json records;
        # read the same manifest bytes and verify them before trusting them.
        manifest_path = version_dir / "files" / "manifest.yml"
        _require(not manifest_path.is_symlink(), "files/manifest.yml must be a regular file")
        manifest_bytes = manifest_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise InvalidPackage(f"cannot read install record or manifest: {exc}") from exc
    _require(isinstance(install, dict) and install.get("package_id") == package_id
             and install.get("version") == version and install.get("archive_sha256") == sha
             and isinstance(install.get("file_digests"), dict), "install.json does not match the active version")
    _require(install["file_digests"].get("manifest.yml") == hashlib.sha256(manifest_bytes).hexdigest(),
             "files/manifest.yml does not match its install.json digest")
    try:
        manifest = yaml.safe_load(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise InvalidPackage(f"cannot parse manifest: {exc}") from exc
    _require(isinstance(manifest, dict), "manifest must be a mapping")
    unknown = set(manifest) - MANIFEST_KEYS
    _require(not unknown, f"unsupported manifest fields: {sorted(unknown)}")
    _require(manifest.get("format") == MANIFEST_FORMAT, "unknown package format")
    format_version = manifest.get("format_version")
    _require(type(format_version) is int and format_version == SUPPORTED_FORMAT_VERSION, "unsupported format_version")
    _require(manifest.get("id") == package_id and str(manifest.get("version")) == version, "manifest id/version mismatch")
    _require(isinstance(manifest.get("name"), str) and 0 < len(manifest["name"].strip()) <= MAX_NAME_LENGTH,
             "manifest name is invalid")
    _optional_text(manifest.get("description"), "description", MAX_DESCRIPTION_LENGTH)
    contributes = manifest.get("contributes")
    _require(isinstance(contributes, dict) and set(contributes) == {"providers"},
             "only contributes.providers is supported")
    providers = contributes["providers"]
    _require(isinstance(providers, list) and bool(providers), "contributes.providers must be a non-empty list")
    package = {"id": package_id, "version": version, "sha256": sha}
    return [_validate_provider(raw, package, targets) for raw in providers]


def load_installed_packages(root: Path, apps_dir: Path = BUILTIN_APPS_DIR) -> InstalledPackages:
    """Read and validate the registry at ``root``; never raises for bad package data."""
    registry_path = root / "registry.json"
    try:
        registry = _read_json(registry_path)
    except (OSError, ValueError) as exc:
        logger.error("[AppPackages] App packages are enabled but %s is unreadable: %s. No packages loaded.",
                     registry_path, exc)
        return EMPTY
    if not (isinstance(registry, dict) and registry.get("format") == REGISTRY_FORMAT
            and isinstance(registry.get("active"), dict)):
        logger.error("[AppPackages] %s has an unsupported structure. No packages loaded.", registry_path)
        return EMPTY

    targets = _BuiltinTargets(apps_dir)
    accepted: List[InstalledProvider] = []
    for package_id, active in sorted(registry["active"].items(), key=lambda item: str(item[0])):
        try:
            contributions = _load_package(root, package_id, active, targets)
            keys = [(p.app_id, p.skill_id, p.provider_id) for p in contributions]
            _require(len(set(keys)) == len(keys), "duplicate provider id within package")
            # Provider ids share one secret namespace, so they are unique across packages.
            taken = {p.provider_id for p in accepted}
            clash = sorted({key[2] for key in keys if key[2] in taken})
            _require(not clash, f"provider ids already provided by another package: {clash}")
        except InvalidPackage as exc:
            logger.error("[AppPackages] Rejected package '%s': %s", package_id, exc)
            continue
        accepted.extend(contributions)
        logger.info("[AppPackages] Loaded %s@%s with %d provider(s)", package_id,
                    contributions[0].package_version, len(contributions))
    return InstalledPackages(providers=tuple(accepted))


def installed_provider_ids(providers: Iterable[InstalledProvider]) -> List[str]:
    return [provider.provider_id for provider in providers]
