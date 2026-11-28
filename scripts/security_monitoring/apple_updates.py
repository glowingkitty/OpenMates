"""Compare Apple package requirements against upstream stable releases for the daily digest."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re

from security_monitoring.inventory import ONNX_REPO, SWIFT_LOCK, apple_package_inventory
from security_monitoring.models import Asset
from security_monitoring.sources import Fetch, FetchError, default_fetch
from security_monitoring.versions import compare_semver

_STABLE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_SHA = re.compile(r"[0-9a-f]{40}")
_GITHUB_PACKAGE = re.compile(r"github\.com/([a-z0-9_.-]+/[a-z0-9_.-]+)")


def _latest(tags: list[str]) -> str:
    versions = [match for tag in tags if (match := _STABLE.fullmatch(tag))]
    if not versions:
        raise FetchError("no_stable_release")
    return max(versions, key=lambda match: tuple(map(int, match.groups()))).group()


def _compare(asset: Asset, fetch: Fetch) -> tuple[str, str] | None:
    current = asset.version
    if not current:
        raise FetchError("missing_version")
    name = asset.name
    if name == ONNX_REPO:
        versions = fetch("https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/index.json", {"timeout": 20})
        latest = _latest(versions["versions"]).lstrip("v")
        if compare_semver(current, latest) == -1:
            return "Update available", f"ONNX Runtime {current} → {latest} (upstream runtime release)"
        return None
    repo_match = _GITHUB_PACKAGE.fullmatch(name)
    if not repo_match:
        raise FetchError("unsupported_repository")
    repo = repo_match.group(1)
    tags = fetch(f"gh:repos/{repo}/tags?per_page=100", {"paginate": False, "timeout": 20})
    latest_tag = _latest([tag["name"] for tag in tags])
    latest = latest_tag.lstrip("v")
    if _SHA.fullmatch(current):
        released = [tag["name"] for tag in tags if tag["commit"]["sha"] == current and _STABLE.fullmatch(tag["name"])]
        if released:
            current = _latest(released).lstrip("v")
        else:
            comparison = fetch(f"gh:repos/{repo}/compare/{current}...{latest_tag}?per_page=1",
                               {"paginate": False, "timeout": 20})
            if comparison["status"] == "ahead":
                return "Update available", f"{repo} {current[:12]} → {latest}"
            if comparison["status"] in {"behind", "identical"}:
                return None
            raise FetchError("revision_not_comparable")
    ordering = compare_semver(current, latest)
    if ordering is None:
        raise FetchError("version_not_comparable")
    if (asset.source_file or "").endswith("(version floor)"):
        return "Unresolved version", f"{repo} floor {current}, latest {latest}"
    if ordering == -1:
        return "Update available", f"{repo} {current} → {latest}"
    return None


def report_lines(root: Path, fetch: Fetch = default_fetch) -> list[tuple[str, str]]:
    """Return digest lines, including explicit gaps when the inputs or upstream fail."""
    inventory = apple_package_inventory(root)
    lines = [("Coverage gap", error) for error in inventory.incomplete_sources]
    if not (root / SWIFT_LOCK).is_file():
        lines.append(("Coverage gap", "No Package.resolved. Swift transitive packages and resolved range versions are unknown."))

    def check(asset: Asset) -> tuple[str, str] | None:
        try:
            return _compare(asset, fetch)
        except FetchError as error:
            return "Not checked", f"{asset.name} ({error.code})"
        except (KeyError, TypeError, ValueError):
            return "Not checked", f"{asset.name} (malformed response)"

    with ThreadPoolExecutor(max_workers=6) as pool:
        findings = [line for line in pool.map(check, inventory.assets) if line is not None]
    return [
        ("APPLE PACKAGES", f"{len(inventory.assets)} package requirements compared with upstream stable releases"),
        *lines, *findings,
    ]
