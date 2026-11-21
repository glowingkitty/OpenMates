"""Scan the container images that actually run, by digest, plus runtime versions.

Covers OS packages and vendored libraries through Trivy (`--pkg-types os,library`)
and reads runtimes Trivy cannot see (node, python3, openssl, caddy, nginx,
brotli) by running each image offline with an overridden entrypoint.

Image sources: dev containers come from the local Docker daemon; core, upload
and preview come from the latest host reports (`deployed_image_digests`,
`{"images": {"<image>": "sha256:..."}}`, or a flat mapping). Server images are
pulled from GHCR by digest; no production server is ever contacted.

Failures are never reported as clean: every result carries `incomplete`
reasons and the CLI says "incomplete coverage" for them. Exit code is 0 even
with findings; non-zero only when a tool failed.

CLI: python3 scripts/security_monitoring/image_scan.py scan [--json] [--role R]
     python3 scripts/security_monitoring/image_scan.py versions [--json] [--role R]
Contract: specifications/architecture/security-monitoring/specification.yml
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring import host_reports
from security_monitoring.config import load_settings
from security_monitoring.models import Asset

# Official Trivy image pinned by digest (release 0.76.1, older than 7 days).
TRIVY_IMAGE = "aquasec/trivy@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c"
TRIVY_CACHE_VOLUME = "openmates-trivy-cache"
CACHE_TTL_SECONDS = 24 * 3600
SCAN_TIMEOUT = 900.0
VERSION_TIMEOUT = 30.0
PULL_TIMEOUT = 600.0
REGISTRY_PREFIX = "ghcr.io/"
ROLE_ENVIRONMENT = {"dev": "dev", "core": "prod", "upload": "upload", "preview": "preview"}
ROLES = tuple(ROLE_ENVIRONMENT)
SEVERITIES = ("critical", "high", "medium", "low", "unknown")
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")

# Prints "<tool>=<raw version output>" for each tool that exists in the image.
VERSION_SCRIPT = """
probe() { command -v "$1" >/dev/null 2>&1 && printf '%s=%s\\n' "$2" "$(eval "$3" 2>&1 | head -n 1)"; }
probe node node 'node --version'
probe node brotli 'node -p process.versions.brotli'
probe python3 python3 'python3 --version'
probe python3 brotli_py 'python3 -c "import brotli;print(brotli.version)"'
probe openssl openssl 'openssl version'
probe caddy caddy 'caddy version'
probe nginx nginx 'nginx -v'
probe brotli brotli 'brotli --version'
true
"""
_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,3}[A-Za-z]?)")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], float], CommandResult]


class ToolFailure(RuntimeError):
    """A docker/trivy invocation failed; coverage for that image is incomplete."""


def subprocess_runner(args: Sequence[str], timeout: float) -> CommandResult:
    try:
        done = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"timeout after {timeout:.0f}s")
    except OSError as error:
        return CommandResult(127, "", str(error))
    return CommandResult(done.returncode, done.stdout, done.stderr)


@dataclass(frozen=True)
class RunningImage:
    ref: str  # human name, e.g. openmates-core-api or ghcr.io/x/y
    digest: str  # sha256:<64 hex>: RepoDigest when known, else image id
    role: str
    environment: str
    source: str  # docker | host-report:<role>
    pull_ref: str | None = None  # set for registry digests that must be pulled first
    local_id: str | None = None  # local image id; trivy resolves ids, not bare repo digests, via the daemon

    @property
    def scan_target(self) -> str:
        return self.pull_ref or self.local_id or self.digest


@dataclass(frozen=True)
class Finding:
    package: str
    installed_version: str
    fixed_version: str | None
    vuln_id: str
    severity: str
    pkg_path: str | None
    image: str
    environments: tuple[str, ...]
    pkg_type: str | None = None
    title: str | None = None


@dataclass
class ScanResult:
    image: str
    digest: str
    role: str
    environments: tuple[str, ...]
    findings: list[Finding] = field(default_factory=list)
    incomplete: str | None = None  # reason when coverage is incomplete
    cached: bool = False


@dataclass
class RuntimeResult:
    image: str
    digest: str
    environments: tuple[str, ...]
    assets: list[Asset] = field(default_factory=list)
    incomplete: str | None = None


# -- running images -----------------------------------------------------------------

def _docker_digest(inspect: Mapping[str, Any], fallback_id: str) -> str:
    for repo_digest in inspect.get("RepoDigests") or []:
        _, _, value = str(repo_digest).partition("@")
        if _SHA.match(value):
            return value
    return fallback_id


def dev_images(runner: Runner) -> list[RunningImage]:
    """Images of the containers running on this (dev) server."""
    listed = runner(["docker", "ps", "--format", "{{.Image}}"], 30)
    if listed.returncode != 0:
        raise ToolFailure(f"docker ps failed: {listed.stderr.strip()[:200]}")
    refs = sorted({line.strip() for line in listed.stdout.splitlines() if line.strip()})
    if not refs:
        return []
    inspected = runner(["docker", "image", "inspect", *refs], 60)
    if inspected.returncode != 0:
        raise ToolFailure(f"docker image inspect failed: {inspected.stderr.strip()[:200]}")
    try:
        records = json.loads(inspected.stdout)
    except json.JSONDecodeError as error:
        raise ToolFailure(f"docker image inspect returned invalid JSON: {error}") from error
    by_digest: dict[str, RunningImage] = {}
    for ref, record in zip(refs, records):
        digest = _docker_digest(record, str(record.get("Id", "")))
        if _SHA.match(digest) and digest not in by_digest:
            by_digest[digest] = RunningImage(ref, digest, "dev", "dev", "docker", None, str(record.get("Id", "")))
    return list(by_digest.values())


def report_images(reports: Mapping[str, Any]) -> tuple[list[RunningImage], list[str]]:
    """Images from the latest host reports; also returns roles without usable data."""
    images: list[RunningImage] = []
    missing: list[str] = []
    for role in ("core", "upload", "preview"):
        report = reports.get(role)
        mapping = (report.contents.get("deployed_image_digests") if report else None)
        if isinstance(mapping, dict) and isinstance(mapping.get("images"), dict):
            mapping = mapping["images"]
        if not isinstance(mapping, dict) or not mapping:
            missing.append(role)
            continue
        for name, digest in sorted(mapping.items()):
            if not _SHA.match(str(digest)):
                missing.append(f"{role}:{name}")
                continue
            base = str(name).split("@")[0].rsplit(":", 1)[0] if re.search(r":[^/]+$", str(name)) else str(name)
            registry = base if "." in base.split("/")[0] else REGISTRY_PREFIX + base
            images.append(RunningImage(str(name), str(digest), role, ROLE_ENVIRONMENT[role],
                                       f"host-report:{role}", f"{registry}@{digest}"))
    return images, missing


def running_images(runner: Runner = subprocess_runner, *, hosts_dir: Path | None = None,
                   roles: Iterable[str] = ROLES) -> tuple[list[RunningImage], list[str]]:
    """All running images for the requested roles and the coverage gaps found."""
    wanted = set(roles)
    images: list[RunningImage] = []
    gaps: list[str] = []
    if "dev" in wanted:
        try:
            images.extend(dev_images(runner))
        except ToolFailure as error:
            gaps.append(f"dev: {error}")
    if wanted & {"core", "upload", "preview"}:
        directory = hosts_dir or load_settings().hosts_dir
        found, missing = report_images(host_reports.load_latest(directory))
        images.extend(image for image in found if image.role in wanted)
        gaps.extend(f"{role}: no image digests reported" for role in missing if role.split(":")[0] in wanted)
    return images, gaps


# -- trivy ----------------------------------------------------------------------------

def trivy_command(target: str, *, local: bool, host_trivy: bool) -> list[str]:
    scan = ["image", "--quiet", "--format", "json", "--scanners", "vuln", "--pkg-types", "os,library",
            "--detection-priority", "comprehensive", "--timeout", "14m", target]
    if host_trivy:
        return ["trivy", *scan]
    mounts = ["-v", f"{TRIVY_CACHE_VOLUME}:/root/.cache/"]
    if local:
        mounts += ["-v", "/var/run/docker.sock:/var/run/docker.sock:ro"]
    return ["docker", "run", "--rm", *mounts, TRIVY_IMAGE, *scan]


def normalize_trivy(document: Mapping[str, Any], image: RunningImage) -> list[Finding]:
    findings: list[Finding] = []
    for result in document.get("Results") or []:
        pkg_type = result.get("Type")
        for vuln in result.get("Vulnerabilities") or []:
            severity = str(vuln.get("Severity", "unknown")).lower()
            path = vuln.get("PkgPath") or (result.get("Target") if result.get("Class") == "lang-pkgs" else None)
            findings.append(Finding(
                package=str(vuln.get("PkgName", "")), installed_version=str(vuln.get("InstalledVersion", "")),
                fixed_version=vuln.get("FixedVersion") or None, vuln_id=str(vuln.get("VulnerabilityID", "")),
                severity=severity if severity in SEVERITIES else "unknown", pkg_path=path or None,
                image=image.ref, environments=(image.environment,), pkg_type=pkg_type,
                title=vuln.get("Title") or None))
    return findings


def _cache_path(state_dir: Path, digest: str) -> Path:
    return state_dir / "image-scans" / f"{digest.replace(':', '_')}.json"


def _read_cache(path: Path, now: float) -> list[dict[str, Any]] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if now - float(record.get("scanned_at", 0)) > CACHE_TTL_SECONDS:
        return None
    return list(record.get("findings", []))


def scan(image: RunningImage, runner: Runner = subprocess_runner, *, state_dir: Path | None = None,
         host_trivy: bool | None = None, now: Callable[[], float] = time.time) -> ScanResult:
    """Scan one image digest; results are cached per digest for 24 hours."""
    result = ScanResult(image.ref, image.digest, image.role, (image.environment,))
    directory = state_dir or load_settings().state_dir
    cache = _cache_path(directory, image.digest)
    cached = _read_cache(cache, now())
    if cached is not None:
        result.findings = [Finding(**{**item, "environments": tuple(item["environments"]),
                                      "image": image.ref}) for item in cached]
        result.environments = (image.environment,)
        result.cached = True
        return result
    if host_trivy is None:
        host_trivy = runner(["which", "trivy"], 10).returncode == 0
    if image.pull_ref:
        pulled = runner(["docker", "pull", "--quiet", image.pull_ref], PULL_TIMEOUT)
        if pulled.returncode != 0:
            result.incomplete = f"pull failed: {pulled.stderr.strip()[:200]}"
            return result
    ran = runner(trivy_command(image.scan_target, local=True, host_trivy=host_trivy), SCAN_TIMEOUT)
    if ran.returncode != 0:
        result.incomplete = f"trivy failed (exit {ran.returncode}): {ran.stderr.strip()[-200:]}"
        return result
    try:
        document = json.loads(ran.stdout)
    except json.JSONDecodeError as error:
        result.incomplete = f"trivy returned invalid JSON: {error}"
        return result
    result.findings = normalize_trivy(document, image)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"scanned_at": now(), "digest": image.digest,
                                 "findings": [asdict(item) for item in result.findings]}), encoding="utf-8")
    return result


def scan_all(images: Iterable[RunningImage], runner: Runner = subprocess_runner, **kwargs: Any) -> list[ScanResult]:
    """Scan each distinct digest once; other roles sharing it are merged into environments."""
    merged: dict[str, ScanResult] = {}
    for image in images:
        done = scan(image, runner, **kwargs)
        existing = merged.get(image.digest)
        if existing is None:
            merged[image.digest] = done
        else:
            existing.environments = tuple(sorted({*existing.environments, *done.environments}))
            existing.findings = [Finding(**{**asdict(f), "environments": existing.environments}) for f in existing.findings]
    return list(merged.values())


# -- runtime versions -------------------------------------------------------------------

def parse_versions(output: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in output.splitlines():
        tool, _, raw = line.partition("=")
        match = _VERSION_RE.search(raw)
        if tool.strip() and match:
            versions[tool.strip()] = match.group(1)
    return versions


def runtime_versions(image: RunningImage, runner: Runner = subprocess_runner) -> RuntimeResult:
    """Run the image offline (no network, read-only, no env) and read runtime versions."""
    result = RuntimeResult(image.ref, image.digest, (image.environment,))
    if image.pull_ref:
        pulled = runner(["docker", "pull", "--quiet", image.pull_ref], PULL_TIMEOUT)
        if pulled.returncode != 0:
            result.incomplete = f"pull failed: {pulled.stderr.strip()[:200]}"
            return result
    command = ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "256m",
               "--entrypoint", "sh", image.scan_target, "-c", VERSION_SCRIPT]
    ran = runner(command, VERSION_TIMEOUT)
    if ran.returncode != 0:
        result.incomplete = f"version probe failed (exit {ran.returncode}): {ran.stderr.strip()[-200:]}"
        return result
    found = parse_versions(ran.stdout)
    names = {"brotli_py": "brotli"}
    for tool, version in sorted(found.items()):
        result.assets.append(Asset(kind="runtime", ecosystem="tool", name=names.get(tool, tool), version=version,
                                   environments=(image.environment,), exposure="internet_facing",
                                   source_file=f"image:{image.ref}@{image.digest}"))
    return result


# -- CLI --------------------------------------------------------------------------------

def _summary(results: Sequence[ScanResult], gaps: Sequence[str]) -> dict[str, Any]:
    counts = {severity: 0 for severity in SEVERITIES}
    for result in results:
        for finding in result.findings:
            counts[finding.severity] += 1
    incomplete = [f"{r.image}: {r.incomplete}" for r in results if r.incomplete] + list(gaps)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "images_scanned": sum(1 for r in results if not r.incomplete),
            "images_total": len(results), "severity_counts": counts, "incomplete_coverage": incomplete}


def _roles(value: str | None) -> tuple[str, ...]:
    return (value,) if value else ROLES


def main(argv: Sequence[str] | None = None, runner: Runner = subprocess_runner) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("scan", "versions"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--role", choices=ROLES)
    args = parser.parse_args(argv)
    images, gaps = running_images(runner, roles=_roles(args.role))
    failed = bool(gaps)
    if args.command == "scan":
        results = scan_all(images, runner)
        summary = _summary(results, gaps)
        failed = bool(summary["incomplete_coverage"])
        if args.json:
            print(json.dumps({**summary, "results": [asdict(r) for r in results]}, indent=1))
        else:
            print(f"images scanned {summary['images_scanned']}/{summary['images_total']} {summary['severity_counts']}")
    else:
        runtime = [runtime_versions(image, runner) for image in images]
        incomplete = [f"{r.image}: {r.incomplete}" for r in runtime if r.incomplete] + gaps
        failed = bool(incomplete)
        if args.json:
            print(json.dumps({"incomplete_coverage": incomplete,
                              "results": [{"image": r.image, "digest": r.digest, "incomplete": r.incomplete,
                                           "assets": [a.to_dict() for a in r.assets]} for r in runtime]}, indent=1))
        else:
            for r in runtime:
                print(r.image, {a.name: a.version for a in r.assets} or r.incomplete)
    if failed:
        print("INCOMPLETE COVERAGE: not a clean result; see incomplete_coverage", file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
