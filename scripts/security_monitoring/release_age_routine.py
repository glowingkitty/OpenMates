"""Routine 7-day release-age check for PyPI, crates.io and container images.

Diffs requirements*.txt, Cargo.lock and Dockerfile/compose image references
between two git refs and fails when any newly introduced or changed version is
younger than 7 days (security-monitoring.release-age.routine). A commit trailer
``Security-Fix: <advisory-id>`` switches the change to the security-fix rule
(at least 72 hours old), and lets registries without a publication-time API
pass with a warning. npm is enforced by pnpm ``minimumReleaseAge``.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
import subprocess
import sys
import tomllib
import urllib.parse
from datetime import datetime, timezone
from typing import Callable

import release_age as policy

Entry = tuple[str, str, str]  # (ecosystem, name, version-or-tag)
CRATES_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;\\#]+)")
FROM_RE = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE)
IMAGE_RE = re.compile(r"^\s*image:\s*[\"']?([^\s\"'#]+)")
TRAILER_RE = re.compile(r"^Security-Fix:\s*(\S+)", re.MULTILINE)
FILE_KINDS = (
    ("requirements*.txt", "pypi"),
    ("Cargo.lock", "cargo"),
    ("Dockerfile*", "docker"),
    ("*.Dockerfile", "docker"),
    ("docker-compose*.y*ml", "docker"),
    ("compose*.y*ml", "docker"),
)

DockerLookup = Callable[[str, str, str | None], "datetime | None"]


def file_kind(path: str) -> str | None:
    base = posixpath.basename(path)
    for pattern, kind in FILE_KINDS:
        if fnmatch.fnmatch(base, pattern):
            return kind
    return None


def parse_requirements(text: str) -> set[Entry]:
    found: set[Entry] = set()
    for line in text.splitlines():
        match = REQ_RE.match(line)
        if match:
            found.add(("PyPI", match.group(1).lower().replace("_", "-"), match.group(2)))
    return found


def parse_cargo_lock(text: str) -> set[Entry]:
    if not text.strip():
        return set()
    packages = tomllib.loads(text).get("package", [])
    return {("crates.io", p["name"], p["version"]) for p in packages if p.get("source") == CRATES_SOURCE}


def split_image(ref: str) -> tuple[str, str, str | None]:
    """Return (image, tag, digest) for a reference; tag is '' when absent."""
    name, _, digest = ref.partition("@")
    last = name.rsplit("/", 1)[-1]
    tag = ""
    if ":" in last:
        name, _, tag = name.rpartition(":")
    return name, tag, digest or None


def parse_images(text: str) -> set[Entry]:
    found: set[Entry] = set()
    stages: set[str] = set()
    for line in text.splitlines():
        from_match = FROM_RE.match(line)
        ref = None
        if from_match:
            ref = from_match.group(1)
            if from_match.group(2):
                stages.add(from_match.group(2).lower())
        else:
            image_match = IMAGE_RE.match(line)
            ref = image_match.group(1) if image_match else None
        if not ref or "$" in ref or ref.lower() == "scratch" or ref.lower() in stages:
            continue
        image, tag, digest = split_image(ref)
        found.add(("docker", image, f"{tag}@{digest}" if digest else tag))
    return found


def parse_entries(kind: str, text: str) -> set[Entry]:
    return {"pypi": parse_requirements, "cargo": parse_cargo_lock, "docker": parse_images}[kind](text)


def changed_entries(kind: str, old_text: str, new_text: str) -> list[Entry]:
    """Entries present in the new text that were absent or different before."""
    return sorted(parse_entries(kind, new_text) - parse_entries(kind, old_text))


def dockerhub_published(image: str, tag: str, digest: str | None) -> datetime | None:
    """Docker Hub tag push time; None for other registries or unverifiable refs."""
    parts = image.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        if parts[0] not in ("docker.io", "registry-1.docker.io"):
            return None
        parts = parts[1:]
    if not tag:
        return None
    if len(parts) == 1:
        parts = ["library", parts[0]]
    path = "/".join(urllib.parse.quote(p) for p in parts)
    doc = policy._fetch_json(f"https://hub.docker.com/v2/repositories/{path}/tags/{urllib.parse.quote(tag)}")
    if not doc:
        return None
    if digest and doc.get("digest") != digest:
        return None
    stamp = doc.get("tag_last_pushed") or doc.get("last_updated")
    return policy.parse_time(stamp) if stamp else None


def evaluate(
    entries: list[tuple[str, Entry]],
    *,
    now: datetime,
    lookup: policy.Lookup,
    docker_lookup: DockerLookup = dockerhub_published,
    security_fix: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return (violations, warnings) for (file, entry) pairs."""
    minimum = policy.SECURITY_AGE if security_fix else policy.ROUTINE_AGE
    rule = f"72h security-fix rule ({security_fix})" if security_fix else "7-day routine rule"
    violations: list[str] = []
    warnings: list[str] = []
    for path, (ecosystem, name, version) in entries:
        label = f"{path}: {ecosystem} {name} {version}"
        try:
            if ecosystem == "docker":
                tag, _, digest = version.partition("@")
                published = docker_lookup(name, tag, digest or None)
            else:
                published = lookup.published_at(ecosystem, name, version)
        except policy.RegistryLookupError as error:
            published, label = None, f"{label} (lookup error: {error})"
        if published is None:
            message = f"{label}: publication time not obtainable"
            if ecosystem == "docker" and security_fix:
                warnings.append(f"{message}; allowed because of Security-Fix {security_fix}")
            else:
                violations.append(f"{message}; failing closed (mark the commit with a Security-Fix trailer only for a real security fix)")
            continue
        age = now - published
        if age < minimum:
            violations.append(f"{label}: published {age.total_seconds() / 86400:.1f} days ago, below the {rule} ({minimum.total_seconds() / 86400:g} days)")
    return violations, warnings


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _git_show(ref: str, path: str) -> str:
    result = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def security_fix_id(base: str, head: str) -> str | None:
    match = TRAILER_RE.search(_git("log", "--format=%B", f"{base}..{head}"))
    return match.group(1) if match else None


def collect(base: str, head: str) -> list[tuple[str, Entry]]:
    entries: list[tuple[str, Entry]] = []
    for path in _git("diff", "--name-only", "--diff-filter=ACMR", base, head).splitlines():
        kind = file_kind(path)
        if kind:
            entries.extend((path, e) for e in changed_entries(kind, _git_show(base, path), _git_show(head, path)))
    return entries


def run(base: str, head: str) -> int:
    entries = collect(base, head)
    fix = security_fix_id(base, head)
    print(f"release-age: {len(entries)} changed dependency/image entries between {base} and {head}" + (f" (Security-Fix {fix})" if fix else ""))
    violations, warnings = evaluate(entries, now=datetime.now(timezone.utc), lookup=policy.NetworkLookup(), security_fix=fix)
    for warning in warnings:
        print(f"::warning::{warning}")
    for violation in violations:
        print(f"::error::{violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "HEAD"))
