"""Explicit asset inventory for automated security monitoring.

Builds a deterministic `Inventory` from lockfiles and manifests (pnpm, npm,
PyPI requirements, pyproject, Cargo, Swift), Dockerfile and compose images,
GitHub Actions references, configured skill providers, fixed vendors, dev-host
tools and OS packages, and the latest host report per server. Technologies we
do not use come from not_used.yml, but an entry that matches anything
inventoried is overridden to used. A required source that fails to read is
listed in `incomplete_sources`; it is never silently skipped. The inventory
holds no addresses or hostnames: host reports contribute only package, kernel,
OS release and image facts. See
specifications/architecture/security-monitoring/specification.yml
(security-monitoring.inventory.explicit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Iterable, Mapping

import yaml

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from audit_frontend_dependency_pins import collect_package_versions  # noqa: E402 - sibling script module, path set above
from security_monitoring.models import Asset, HostReport, Inventory  # noqa: E402 - package import after path setup

try:
    from packaging.requirements import InvalidRequirement, Requirement
except ImportError:  # pragma: no cover - fallback parser handles hosts without packaging
    Requirement = None  # type: ignore[assignment,misc]  # optional dependency marker
    InvalidRequirement = ValueError  # type: ignore[assignment,misc]  # keeps except clauses valid

NOT_USED_PATH = Path(__file__).with_name("not_used.yml")
HOST_REPORT_MAX_AGE = timedelta(hours=36)
ROLE_ENVIRONMENT = {"core": "prod", "upload": "upload", "preview": "preview"}
EXPOSURE_RANK = {"internet_facing": 3, "internal": 2, "client_only": 1, "build_only": 0}
IGNORED_DIRS = {".git", ".openmates-agent-worktrees", ".pnpm-store", "node_modules", "test-results",
                ".venv", "venv", "dist", "build", "target", ".build", "__pycache__", "docs"}
CARGO_LOCKS = {
    "Cargo.lock": (("dev", "ci", "apple_client"), "client_only"),
    "frontend/packages/openmates-tui-prototype/Cargo.lock": (("dev",), "build_only"),
}
FIXED_VENDORS = (
    ("Hetzner", ("prod", "upload", "preview", "dev"), "internet_facing"),
    ("Vercel", ("vercel",), "internet_facing"),
    ("GitHub", ("ci",), "build_only"),
)
# Dev-host tools: binary name -> npm package that may provide it globally.
DEV_TOOLS = {
    "claude": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
    "cursor-agent": None,
    "gemini": "@google/gemini-cli",
    "opencode": "opencode-ai",
    "aider": None,
    "vercel": "vercel",
    "cloudflared": None,
    "vscode-server": None,
    "tailscale": None,
}
_VERSION_IN_TEXT = re.compile(r"\b(\d+\.\d+(?:\.\d+)?(?:[-+.][0-9A-Za-z.-]+)?)\b")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_USES_RE = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
_FROM_RE = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE)
_ARG_RE = re.compile(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)", re.IGNORECASE)
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_PBX_BLOCK_RE = re.compile(r"XCRemoteSwiftPackageReference \"[^\"]*\" \*/ = \{(.*?)\n\t\t\};", re.DOTALL)
_PARSE_ERRORS = (OSError, ValueError, UnicodeDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError, KeyError, TypeError)


class SourceUnreadable(ValueError):
    """A required inventory source exists but cannot be interpreted."""


@dataclass(frozen=True)
class NotUsedEntry:
    name: str
    aliases: tuple[str, ...]
    reason: str

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


def is_sha_pinned(asset: Asset) -> bool:
    """True for a GitHub Actions reference pinned to a full commit SHA."""
    return asset.kind == "ci_action" and bool(asset.version and _SHA_RE.match(asset.version))


def normalize_term(value: str) -> str:
    return re.sub(r"[\s_.]+", "-", value.strip().lower())


def load_not_used(path: Path = NOT_USED_PATH) -> list[NotUsedEntry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise SourceUnreadable("not_used.yml must contain an entries list")
    entries = []
    for raw in data["entries"]:
        if not isinstance(raw, dict) or not raw.get("name") or not str(raw.get("reason") or "").strip():
            raise SourceUnreadable("every not_used entry needs a name and a reason")
        aliases = tuple(str(alias) for alias in raw.get("aliases") or ())
        entries.append(NotUsedEntry(str(raw["name"]), aliases, str(raw["reason"]).strip()))
    return entries


def _term_hits_asset(term: str, asset: Asset) -> bool:
    name = normalize_term(asset.name.rsplit("/", 1)[-1] if asset.kind == "package" else asset.name)
    full = normalize_term(asset.name)
    if term in (name, full):
        return True
    if asset.kind in {"os_package", "dev_tool", "container_image", "vendor", "skill_provider", "runtime"}:
        for candidate in (name, full):
            if candidate.startswith(term + "-"):
                return True
            if candidate.startswith(term) and len(candidate) > len(term) and candidate[len(term)].isdigit():
                return True
    return False


def resolve_not_used(entries: Iterable[NotUsedEntry], used_assets: Iterable[Asset]) -> tuple[list[NotUsedEntry], list[NotUsedEntry]]:
    """Split not-used entries into (kept, overridden-because-installed)."""
    used = [asset for asset in used_assets if asset.usage == "used"]
    kept: list[NotUsedEntry] = []
    overridden: list[NotUsedEntry] = []
    for entry in entries:
        terms = [normalize_term(term) for term in entry.terms]
        if any(_term_hits_asset(term, asset) for term in terms for asset in used):
            overridden.append(entry)
        else:
            kept.append(entry)
    return kept, overridden


class DevHostProbe:
    """Reads the dev host's own tools and OS packages. Tests replace this."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()

    def which(self, name: str) -> Path | None:
        if name == "vscode-server":
            marker = self.home / ".vscode-server"
            return marker if marker.is_dir() else None
        extra = os.pathsep.join(str(self.home / sub) for sub in (".local/bin", ".npm-global/bin"))
        found = shutil.which(name, path=os.environ.get("PATH", "") + os.pathsep + extra)
        return Path(found) if found else None

    def npm_global_packages(self) -> dict[str, str]:
        root = self.home / ".npm-global" / "lib" / "node_modules"
        packages: dict[str, str] = {}
        if not root.is_dir():
            return packages
        for manifest in sorted(root.glob("*/package.json")) + sorted(root.glob("@*/*/package.json")):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("name") and data.get("version"):
                packages[str(data["name"])] = str(data["version"])
        return packages

    def tool_version(self, name: str, path: Path) -> str | None:
        if name == "vscode-server":
            versions = sorted(path.glob("cli/servers/*/server/package.json"))
            if versions:
                data = json.loads(versions[-1].read_text(encoding="utf-8"))
                return str(data.get("version")) if isinstance(data, dict) and data.get("version") else None
            return None
        resolved = str(path.resolve())
        marker = re.search(r"/versions/([^/]+)/", resolved + "/")
        if marker:
            return marker.group(1)
        try:
            result = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        match = _VERSION_IN_TEXT.search(result.stdout or result.stderr or "")
        return match.group(1) if match else None

    def dpkg_packages(self) -> dict[str, str]:
        result = subprocess.run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${db:Status-Abbrev}\n"],
                                capture_output=True, text=True, timeout=60, check=True)
        packages: dict[str, str] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[1] and parts[2].startswith("ii"):
                packages[parts[0].split(":", 1)[0]] = parts[1]
        if not packages:
            raise SourceUnreadable("dpkg-query returned no installed packages")
        return packages

    def kernel(self) -> str:
        return subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=10, check=True).stdout.strip()

    def os_release(self) -> str:
        return Path("/etc/os-release").read_text(encoding="utf-8")


dev_host_probe: type[DevHostProbe] = DevHostProbe


class _Builder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.assets: list[Asset] = []
        self.incomplete: list[str] = []

    def add(self, kind: str, ecosystem: str, name: str, version: str | None, environments: Iterable[str],
            exposure: str, source_file: str | None) -> None:
        self.assets.append(Asset(kind=kind, ecosystem=ecosystem, name=name, version=version or None,  # type: ignore[arg-type]  # validated literals
                                 environments=tuple(sorted(set(environments))), exposure=exposure,  # type: ignore[arg-type]  # validated literals
                                 source_file=source_file))

    def guard(self, label: str, reader, *args) -> None:
        try:
            reader(*args)
        except (SourceUnreadable, subprocess.CalledProcessError, subprocess.TimeoutExpired, *_PARSE_ERRORS) as error:
            self.incomplete.append(f"{label}: {type(error).__name__}")

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def walk(self, start: Path, predicate) -> list[Path]:
        found: list[Path] = []
        if not start.is_dir():
            return found
        for directory, children, files in os.walk(start):
            children[:] = sorted(child for child in children if child not in IGNORED_DIRS)
            found.extend(Path(directory) / name for name in sorted(files) if predicate(name))
        return found


# -- language package sources ---------------------------------------------------

def _read_pnpm(builder: _Builder) -> None:
    path = builder.root / "pnpm-lock.yaml"
    packages = collect_package_versions(path.read_text(encoding="utf-8"))
    if not packages:
        raise SourceUnreadable("no packages section entries")
    for name, versions in packages.items():
        for version in versions:
            builder.add("package", "npm", name, version.split("(", 1)[0], ("vercel", "dev"), "internet_facing", "pnpm-lock.yaml")


def _read_package_lock(builder: _Builder, relative: str, environments: tuple[str, ...], exposure: str) -> None:
    data = json.loads((builder.root / relative).read_text(encoding="utf-8"))
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        raise SourceUnreadable("package-lock.json without packages map")
    for key, entry in packages.items():
        if not key or not isinstance(entry, dict) or not entry.get("version") or entry.get("link"):
            continue
        name = entry.get("name") or key.rsplit("node_modules/", 1)[-1]
        builder.add("package", "npm", str(name), str(entry["version"]), environments, exposure, relative)


def _requirement_coordinates(line: str) -> tuple[str, str | None] | None:
    text = re.split(r"\s+#", line, maxsplit=1)[0].strip()
    if not text or text.startswith(("#", "-")):
        return None
    if Requirement is not None:
        try:
            requirement = Requirement(text)
        except InvalidRequirement as error:
            raise SourceUnreadable(f"invalid requirement line: {error}") from error
        specs = list(requirement.specifier)
        exact = specs[0].version if len(specs) == 1 and specs[0].operator in {"==", "==="} and "*" not in specs[0].version else None
        return requirement.name, exact
    match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(?:(==)\s*([^\s,;]+)|[<>=!~]|@|;|$)", text)
    if not match:
        raise SourceUnreadable("unparseable requirement line")
    return match.group(1), match.group(3) if match.group(2) else None


def _requirements_scope(relative: str) -> tuple[tuple[str, ...], str]:
    if Path(relative).name.startswith("requirements-dev"):
        return ("dev", "ci"), "build_only"
    for prefix, scope in (("backend/upload/", (("upload",), "internet_facing")),
                          ("backend/preview/", (("preview",), "internet_facing")),
                          ("backend/engineering_control_plane/", (("dev",), "internal"))):
        if relative.startswith(prefix):
            return scope
    return ("prod", "dev"), "internet_facing"


def _read_requirements(builder: _Builder, path: Path) -> None:
    relative = builder.rel(path)
    environments, exposure = _requirements_scope(relative)
    for line in path.read_text(encoding="utf-8").splitlines():
        coordinates = _requirement_coordinates(line)
        if coordinates:
            builder.add("package", "PyPI", coordinates[0], coordinates[1], environments, exposure, relative)


def _read_pyproject(builder: _Builder) -> None:
    relative = "packages/openmates-python/pyproject.toml"
    data = tomllib.loads((builder.root / relative).read_text(encoding="utf-8"))
    for line in data["project"].get("dependencies", []):
        coordinates = _requirement_coordinates(str(line))
        if coordinates:
            builder.add("package", "PyPI", coordinates[0], coordinates[1], ("dev",), "client_only", relative)


def _read_cargo(builder: _Builder, relative: str, environments: tuple[str, ...], exposure: str) -> None:
    data = tomllib.loads((builder.root / relative).read_text(encoding="utf-8"))
    packages = data.get("package")
    if not isinstance(packages, list):
        raise SourceUnreadable("Cargo.lock without package entries")
    for package in packages:
        if str(package.get("source", "")).startswith("registry+"):
            builder.add("package", "crates.io", str(package["name"]), str(package["version"]), environments, exposure, relative)


def _swift_name(url: str) -> str:
    return re.sub(r"\.git$", "", re.sub(r"^https?://", "", url.strip().rstrip("/")))


def _read_swift(builder: _Builder) -> None:
    project = builder.root / "apple/OpenMates.xcodeproj/project.pbxproj"
    resolved_path = builder.root / "apple/OpenMates.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
    pins: dict[str, str] = {}
    if resolved_path.is_file():
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        for pin in resolved.get("pins") or resolved.get("object", {}).get("pins", []):
            location = pin.get("location") or pin.get("repositoryURL")
            state = pin.get("state") or {}
            if location and (state.get("version") or state.get("revision")):
                pins[_swift_name(location)] = str(state.get("version") or state.get("revision"))
    text = project.read_text(encoding="utf-8")
    blocks = _PBX_BLOCK_RE.findall(text)
    if "XCRemoteSwiftPackageReference" in text and not blocks:
        raise SourceUnreadable("Swift package references could not be parsed")
    for block in blocks:
        url = re.search(r"repositoryURL = \"([^\"]+)\"", block)
        if not url:
            raise SourceUnreadable("Swift package reference without repositoryURL")
        name = _swift_name(url.group(1))
        exact = re.search(r"kind = exactVersion;\s*version = \"?([^\";]+)\"?;", block)
        revision = re.search(r"revision = \"?([0-9a-f]{7,40})\"?;", block)
        version = pins.get(name) or (exact.group(1) if exact else revision.group(1) if revision else None)
        builder.add("package", "SwiftURL", name, version, ("apple_client",), "client_only", "apple/OpenMates.xcodeproj")


# -- images, CI, providers, vendors ---------------------------------------------

def _image_scope(relative: str) -> tuple[tuple[str, ...], str] | None:
    lowered = relative.lower()
    if "selfhost" in lowered:
        return None  # distributed self-host templates, not run by OpenMates
    rules = (("backend/upload/", (("upload",), "internet_facing")),
             ("backend/preview/", (("preview",), "internet_facing")),
             ("backend/engineering_control_plane/", (("dev",), "internal")),
             ("deployment/engineering_control_plane/", (("dev",), "internal")),
             ("docker-compose.playwright", (("ci",), "build_only")),
             ("backend/", (("prod", "dev"), "internet_facing")),
             ("frontend/apps/", (("prod", "dev"), "internet_facing")))
    for prefix, scope in rules:
        if lowered.startswith(prefix):
            return scope
    return None


def _resolve_vars(value: str, defaults: Mapping[str, str]) -> str | None:
    unresolved = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group(1) or match.group(3)
        if name in defaults:
            return defaults[name]
        if match.group(2) is not None:
            return match.group(2)
        unresolved = True
        return ""

    resolved = _VAR_RE.sub(substitute, value)
    return None if unresolved else resolved


def split_image_reference(reference: str) -> tuple[str, str | None]:
    """`name[:tag][@digest]` -> (normalized name, `tag[@digest]` or None)."""
    name, _, digest = reference.partition("@")
    tag = None
    last = name.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = name.rsplit(":", 1)
    for prefix in ("docker.io/", "index.docker.io/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.startswith("library/"):
        name = name[len("library/"):]
    version = "@".join(part for part in (tag, digest) if part) or None
    return name, version


def _add_image(builder: _Builder, reference: str, scope: tuple[tuple[str, ...], str], relative: str) -> None:
    name, version = split_image_reference(reference)
    if name == "scratch" or name.startswith("openmates"):
        return  # locally built images are covered by their own Dockerfiles
    builder.add("container_image", "docker", name, version, scope[0], scope[1], relative)


def dockerfile_instructions(text: str) -> list[str]:
    """Logical Dockerfile instructions; continuation lines joined, heredoc bodies skipped."""
    instructions: list[str] = []
    pending = ""
    heredoc: str | None = None
    for raw in text.splitlines():
        if heredoc is not None:
            if raw.strip() == heredoc:
                heredoc = None
            continue
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        logical = (pending + line).strip()
        pending = ""
        if logical:
            instructions.append(logical)
            marker = _HEREDOC_RE.search(logical)
            if marker and not logical.upper().startswith("FROM"):
                heredoc = marker.group(1)
    if pending.strip():
        instructions.append(pending.strip())
    return instructions


def _read_dockerfile(builder: _Builder, path: Path) -> None:
    relative = builder.rel(path)
    scope = _image_scope(relative)
    if scope is None:
        return
    instructions = dockerfile_instructions(path.read_text(encoding="utf-8"))
    defaults: dict[str, str] = {}
    for instruction in instructions:
        arg = _ARG_RE.match(instruction)
        if arg:
            defaults.setdefault(arg.group(1), arg.group(2).strip("\"'"))
    stages: set[str] = set()
    for reference, stage in (m.groups() for m in map(_FROM_RE.match, instructions) if m):
        resolved = _resolve_vars(reference, defaults)
        if resolved is None:
            raise SourceUnreadable(f"FROM with unresolved build argument: {reference}")
        if resolved.lower() not in stages:
            _add_image(builder, resolved, scope, relative)
        if stage:
            stages.add(stage.lower())


def _read_compose(builder: _Builder, path: Path) -> None:
    relative = builder.rel(path)
    scope = _image_scope(relative)
    if scope is None:
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services") or {} if isinstance(data, dict) else None
    if not isinstance(services, dict):
        raise SourceUnreadable("compose file without services map")
    for service in services.values():
        image = service.get("image") if isinstance(service, dict) else None
        if not image:
            continue
        resolved = _resolve_vars(str(image), {})
        if resolved is None:
            raise SourceUnreadable(f"image with unresolved variable: {image}")
        _add_image(builder, resolved, scope, relative)


def _read_actions(builder: _Builder) -> None:
    github = builder.root / ".github"
    files = builder.walk(github, lambda name: name.endswith((".yml", ".yaml")))
    if not files:
        raise SourceUnreadable("no workflow files found")
    for path in files:
        for reference in _USES_RE.findall(path.read_text(encoding="utf-8")):
            if reference.startswith(("./", "docker://")) or "@" not in reference:
                continue
            action, ref = reference.rsplit("@", 1)
            name = "/".join(action.split("/")[:2])
            builder.add("ci_action", "github-actions", name, ref, ("ci",), "build_only", builder.rel(path))


def _read_providers(builder: _Builder) -> None:
    files = sorted((builder.root / "backend/providers").glob("*.yml"))
    if not files:
        raise SourceUnreadable("no provider configuration files")
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not (data.get("name") or data.get("provider_id")):
            raise SourceUnreadable(f"{builder.rel(path)} has no provider name")
        builder.add("skill_provider", "vendor", str(data.get("name") or data["provider_id"]), None,
                    ("prod", "dev"), "internal", builder.rel(path))


# -- hosts ------------------------------------------------------------------------

def _os_release_fields(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key).upper(): str(item) for key, item in value.items()}
    if isinstance(value, str):
        fields = {}
        for line in value.splitlines():
            key, sep, item = line.partition("=")
            if sep:
                fields[key.strip().upper()] = item.strip().strip('"')
        return fields
    raise SourceUnreadable("os_release has an unsupported type")


def _add_os_assets(builder: _Builder, environment: str, release: Mapping[str, str], kernel: str | None,
                   packages: Mapping[str, str], source: str) -> None:
    distro = (release.get("ID") or "linux").lower()
    if release.get("VERSION_ID"):
        builder.add("runtime", "os", distro, release["VERSION_ID"], (environment,), "internet_facing", source)
    if kernel:
        builder.add("kernel", distro, "linux-kernel", kernel, (environment,), "internet_facing", source)
    for name, version in packages.items():
        builder.add("os_package", distro, str(name), str(version), (environment,), "internet_facing", source)


def _read_dev_host(builder: _Builder, probe: DevHostProbe) -> None:
    release = _os_release_fields(probe.os_release())
    _add_os_assets(builder, "dev", release, probe.kernel(), probe.dpkg_packages(), "dev-host")


def _read_dev_tools(builder: _Builder, probe: DevHostProbe) -> None:
    npm_packages = probe.npm_global_packages()
    for name, version in npm_packages.items():
        builder.add("package", "npm", name, version, ("dev_tools",), "internal", "dev-host:npm-global")
    for tool in DEV_TOOLS:
        path = probe.which(tool)
        package = DEV_TOOLS[tool]
        if path is not None:
            builder.add("dev_tool", "tool", tool, probe.tool_version(tool, path), ("dev_tools",), "internal", "dev-host:path")
        elif package and package in npm_packages:
            builder.add("dev_tool", "tool", tool, npm_packages[package], ("dev_tools",), "internal", "dev-host:npm-global")


def _host_report_age(report: HostReport, now: datetime) -> timedelta | None:
    try:
        generated = datetime.fromisoformat(report.generated_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return now - generated


def _read_host_report(builder: _Builder, role: str, report: HostReport) -> None:
    environment = ROLE_ENVIRONMENT[role]
    contents = report.contents
    packages = contents.get("package_versions")
    if not isinstance(packages, dict) or not packages:
        raise SourceUnreadable("package_versions missing or empty")
    release = _os_release_fields(contents.get("os_release") or {})
    kernel = contents.get("running_kernel")
    _add_os_assets(builder, environment, release, str(kernel) if kernel else None, packages, f"host-report:{role}")
    images = contents.get("deployed_image_digests")
    if images is None:
        return
    if not isinstance(images, dict):
        raise SourceUnreadable("deployed_image_digests must be a mapping")
    for image, digest in images.items():
        name, version = split_image_reference(str(image))
        builder.add("container_image", "docker", name, str(digest) if digest else version,
                    (environment,), "internet_facing", f"host-report:{role}")


# -- assembly ---------------------------------------------------------------------

def _merge(assets: Iterable[Asset]) -> tuple[Asset, ...]:
    merged: dict[tuple[str, str, str, str | None, str], Asset] = {}
    for asset in assets:
        key = (asset.kind, asset.ecosystem, asset.name.lower(), asset.version, asset.usage)
        existing = merged.get(key)
        if existing is None:
            merged[key] = asset
            continue
        exposure = max((existing.exposure, asset.exposure), key=lambda value: EXPOSURE_RANK[value])
        sources = sorted({part for part in f"{existing.source_file or ''},{asset.source_file or ''}".split(",") if part})
        merged[key] = Asset(kind=existing.kind, ecosystem=existing.ecosystem, name=existing.name, version=existing.version,
                            environments=tuple(sorted(set(existing.environments) | set(asset.environments))),
                            exposure=exposure, usage=existing.usage, not_used_reason=existing.not_used_reason,
                            source_file=",".join(sources) or None)
    return tuple(sorted(merged.values(), key=lambda item: (item.identity, item.kind, item.environments)))


def build_inventory(project_root: Path, host_reports: Mapping[str, HostReport | None], now: datetime) -> Inventory:
    """Regenerate the explicit inventory from the repository, dev host and host reports."""
    root = Path(project_root)
    builder = _Builder(root)
    builder.guard("pnpm-lock.yaml", _read_pnpm, builder)
    builder.guard("backend/status/frontend/package-lock.json", _read_package_lock, builder,
                  "backend/status/frontend/package-lock.json", ("prod", "dev"), "internet_facing")
    requirement_files = builder.walk(root / "backend", lambda name: name.startswith("requirements") and name.endswith(".txt"))
    if not requirement_files:
        builder.incomplete.append("backend/**/requirements*.txt: none found")
    for path in requirement_files:
        builder.guard(builder.rel(path), _read_requirements, builder, path)
    builder.guard("packages/openmates-python/pyproject.toml", _read_pyproject, builder)
    for relative, (environments, exposure) in CARGO_LOCKS.items():
        builder.guard(relative, _read_cargo, builder, relative, environments, exposure)
    builder.guard("apple/OpenMates.xcodeproj", _read_swift, builder)
    image_roots = [root / "backend", root / "deployment", root / "frontend" / "apps"]
    dockerfiles = [path for start in image_roots for path in builder.walk(start, lambda name: name.startswith("Dockerfile"))]
    composes = [path for start in image_roots for path in builder.walk(start, lambda name: "compose" in name and name.endswith((".yml", ".yaml")))]
    composes += sorted(root.glob("docker-compose*.yml"))
    if not dockerfiles:
        builder.incomplete.append("Dockerfile: none found")
    for path in dockerfiles:
        builder.guard(builder.rel(path), _read_dockerfile, builder, path)
    for path in composes:
        builder.guard(builder.rel(path), _read_compose, builder, path)
    builder.guard(".github actions", _read_actions, builder)
    builder.guard("backend/providers", _read_providers, builder)
    for name, environments, exposure in FIXED_VENDORS:
        builder.add("vendor", "vendor", name, None, environments, exposure, "fixed-vendor")

    probe = dev_host_probe()
    builder.guard("dev-host:os", _read_dev_host, builder, probe)
    builder.guard("dev-host:tools", _read_dev_tools, builder, probe)

    stale: list[str] = []
    for role in sorted(ROLE_ENVIRONMENT):
        report = host_reports.get(role)
        age = _host_report_age(report, now) if report is not None else None
        if report is None or age is None or age > HOST_REPORT_MAX_AGE:
            stale.append(role)
            continue
        builder.guard(f"host-report:{role}", _read_host_report, builder, role, report)

    used = _merge(builder.assets)
    try:
        kept, _overridden = resolve_not_used(load_not_used(), used)
    except (SourceUnreadable, *_PARSE_ERRORS) as error:
        builder.incomplete.append(f"not_used.yml: {type(error).__name__}")
        kept = []
    not_used = [Asset(kind="vendor", ecosystem="not_used", name=entry.name, version=None, environments=(),
                      exposure="internal", usage="not_used", not_used_reason=entry.reason,
                      source_file="scripts/security_monitoring/not_used.yml") for entry in kept]
    return Inventory(
        generated_at=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        assets=used + tuple(not_used),
        incomplete_sources=tuple(builder.incomplete),
        stale_hosts=tuple(stale),
    )
