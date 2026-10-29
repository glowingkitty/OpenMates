"""Canonical exact-source SDK authority selection; never candidate authority.

The public default loader is unchanged. Only a canonical committed registration
can select a separately reviewed full manifest for one immutable source.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

REGISTRY = "scripts/ci_sdk_candidate_authorities.json"
MANIFESTS = "scripts/ci_sdk_candidate_authorities"
CANDIDATE_MANIFEST = "scripts/ci_sdk_conformance_trust.json"
REGISTRY_LIMIT = 64 * 1024
MANIFEST_LIMIT = 2 * 1024**2


def _git(root, *args):
    # Explicit cwd and clean Git routing; no candidate/environment-selected
    # object database, replacement object, config, command or authority path.
    result = subprocess.run(
        ["/usr/bin/git", "--no-replace-objects", "-C", str(root), *args],
        env={
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=True,
    )
    return result.stdout


def _blob(root, revision, name, limit, require, *, optional=False):
    listing = _git(root, "ls-tree", "-z", revision, "--", name)
    if optional and listing == b"":
        return None
    require(
        len(listing) <= 1024 and listing.endswith(b"\0"), "candidate_authority_git_file"
    )
    rows = listing[:-1].split(b"\0")
    require(len(rows) == 1, "candidate_authority_git_file")
    meta, actual = rows[0].split(b"\t", 1)
    mode, kind, oid = meta.split()
    require(
        mode == b"100644" and kind == b"blob" and actual.decode() == name,
        "candidate_authority_git_file",
    )
    size = int(_git(root, "cat-file", "-s", oid.decode()).strip())
    require(0 < size <= limit, "candidate_authority_size")
    raw = _git(root, "cat-file", "blob", oid.decode())
    require(len(raw) == size, "candidate_authority_git_file")
    return raw


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate canonical authority field")
        result[name] = value
    return result


def _document(raw, require):
    try:
        value = json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, UnicodeError):
        require(False, "candidate_authority_schema")
    require(type(value) is dict, "candidate_authority_schema")
    return value


def _registration(raw, source, require):
    registry = _document(raw, require)
    require(
        set(registry) == {"schemaVersion", "registrations"}
        and type(registry["schemaVersion"]) is int
        and registry["schemaVersion"] == 1,
        "candidate_authority_schema",
    )
    entries = registry["registrations"]
    require(type(entries) is list, "candidate_authority_schema")
    selected = None
    sources = set()
    for entry in entries:
        require(
            type(entry) is dict
            and set(entry) == {"sourceCommit", "sourceTree", "authoritySha256"},
            "candidate_authority_schema",
        )
        for key, width in (
            ("sourceCommit", 40),
            ("sourceTree", 40),
            ("authoritySha256", 64),
        ):
            require(
                isinstance(entry[key], str)
                and re.fullmatch(r"[0-9a-f]{%d}" % width, entry[key]),
                "candidate_authority_schema",
            )
        require(entry["sourceCommit"] not in sources, "candidate_authority_conflict")
        sources.add(entry["sourceCommit"])
        if entry["sourceCommit"] == source:
            selected = entry
    return selected


def select_trust(
    root, source, *, load_default, regular, require, checkout=False, harness=None
):
    """Select canonical authority; root/source are existing controller identities.

    Result retrieval passes its already verified original harness revision.
    No authority hash/path, caller JSON or environment selector exists.
    Unregistered historical sources use only that revision's public default.
    """
    require(
        isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source),
        "source_identity",
    )
    require(type(checkout) is bool, "source_identity")
    canonical = Path(__file__).resolve().parents[1]
    require(
        Path(_git(canonical, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        == canonical,
        "candidate_authority_harness",
    )
    current = _git(canonical, "rev-parse", "HEAD").decode().strip()
    revision = current if harness is None else harness
    require(
        isinstance(revision, str)
        and re.fullmatch(r"[0-9a-f]{40}", revision)
        and _git(canonical, "rev-parse", revision + "^{commit}").decode().strip()
        == revision,
        "candidate_authority_harness",
    )
    # The requested original harness owns both selection and default authority.
    # A later registry/default cannot change a historical job's interpretation.
    registry_raw = _blob(
        canonical, revision, REGISTRY, REGISTRY_LIMIT, require, optional=True
    )
    if registry_raw is not None and revision == current:
        require(
            regular(canonical / REGISTRY, REGISTRY_LIMIT) == registry_raw,
            "candidate_authority_registry_changed",
        )
    entry = (
        _registration(registry_raw, source, require)
        if registry_raw is not None
        else None
    )
    if entry is None:
        if harness is None:
            return load_default()
        # Old public jobs can predate registration, including jobs for a source
        # registered later. Preserve their original public manifest bytes.
        return _document(
            _blob(canonical, revision, CANDIDATE_MANIFEST, MANIFEST_LIMIT, require),
            require,
        )
    require(
        _git(root, "rev-parse", source + "^{commit}").decode().strip() == source,
        "source_identity",
    )
    require(
        _git(root, "rev-parse", source + "^{tree}").decode().strip()
        == entry["sourceTree"],
        "candidate_authority_source_tree",
    )
    name = MANIFESTS + "/" + entry["authoritySha256"] + ".json"
    canonical_raw = _blob(canonical, revision, name, MANIFEST_LIMIT, require)
    if revision == current:
        require(
            regular(canonical / name, MANIFEST_LIMIT) == canonical_raw,
            "candidate_authority_manifest_changed",
        )
    require(
        hashlib.sha256(canonical_raw).hexdigest() == entry["authoritySha256"],
        "candidate_authority_manifest_changed",
    )
    candidate_raw = _blob(root, source, CANDIDATE_MANIFEST, MANIFEST_LIMIT, require)
    require(candidate_raw == canonical_raw, "candidate_authority_source_manifest")
    if checkout:
        require(
            _git(root, "rev-parse", "HEAD").decode().strip() == source,
            "source_identity",
        )
        require(
            regular(root / CANDIDATE_MANIFEST, MANIFEST_LIMIT) == candidate_raw,
            "candidate_authority_checkout_changed",
        )
    return _document(canonical_raw, require)
