"""Trusted, read-only production inventory binding after existing web readiness.

No build, account data, raw subprocess diagnostics or ambient performance claims.
The candidate inventory program must exactly match the reviewed byte pin; run a
private copy, never an unchecked mutable candidate program. Caller already attests
Node via ci_run_tests.verify_pinned_node_runtime. Missing proof is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

PERFORMANCE_SPECS = frozenset({
    "page-load-performance.spec.ts", "chat-streaming-render-performance.spec.ts",
})
TOOL_SHA256 = "8d0c6ae82c3366a4dd3753803159fa256d520ec1f137b32d05d7808d5008cfb9"
MAX_FILES, MAX_FILE, MAX_TOTAL = 20000, 32 * 1024**2, 512 * 1024**2


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_regular(path, limit):
    if path.resolve() != path:
        raise ValueError("unsafe_path")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_size > limit
                or before.st_mode & 0o002 or before.st_uid not in (0, os.getuid())):
            raise ValueError("unsafe_file")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        # Deliberately exclude atime, which our own reads may change.
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_mode, s.st_size,
                    s.st_uid, s.st_gid, s.st_nlink, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) > limit or identity(before) != identity(after) or identity(after) != identity(path.lstat()):
            raise ValueError("changed_file")
        return data


def build_snapshot(build):
    if build.resolve() != build or not build.is_dir():
        raise ValueError("missing_build")
    rows, total = {}, 0
    for directory, dirs, files in os.walk(build, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("unsafe_build")
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(build).as_posix()
            if not re.fullmatch(r"[A-Za-z0-9_.@/-]{1,512}", relative):
                raise ValueError("unsafe_build")
            data = read_regular(path, MAX_FILE)
            total += len(data)
            rows[relative] = {"sha256": digest(data), "rawBytes": len(data)}
            if len(rows) > MAX_FILES or total > MAX_TOTAL:
                raise ValueError("oversize_build")
    return rows



def reconcile_inventory(inventory, snapshot):
    """Every public report row must describe the trusted pre-inventory bytes.

    Pre/post tree equality alone misses transient alternate trees. The pinned
    tool hashes/compresses each row from one byte buffer, so reconciling all row
    hashes/sizes also binds those compression estimates to the snapshot.
    """
    expected = {name: value for name, value in snapshot.items()
                if not re.search(r"\.(gz|br)$", name)}
    assets = inventory.get("assets")
    if not isinstance(assets, list) or len(assets) != len(expected):
        raise ValueError("asset_set")
    seen, identities = set(), []
    totals = {kind: {"count": 0, "rawBytes": 0, "gzipBytes": 0, "brotliBytes": 0}
              for kind in ("javascript", "wasm", "other")}
    for row in assets:
        if not isinstance(row, dict) or set(row) != {"path", "kind", "sha256", "rawBytes", "gzipBytes", "brotliBytes"}:
            raise ValueError("asset_row")
        name = row["path"]
        if not isinstance(name, str) or name not in expected or name in seen:
            raise ValueError("asset_path")
        seen.add(name)
        kind = ("javascript" if re.search(r"\.m?js$", name, re.I)
                else "wasm" if re.search(r"\.wasm$", name, re.I) else "other")
        if (row["kind"] != kind or row["sha256"] != expected[name]["sha256"]
                or type(row["rawBytes"]) is not int or row["rawBytes"] != expected[name]["rawBytes"]
                or any(type(row[key]) is not int or not 0 <= row[key] <= MAX_FILE + 65536
                       for key in ("gzipBytes", "brotliBytes"))):
            raise ValueError("asset_content")
        identities.append({"path": name, "sha256": row["sha256"]})
        totals[kind]["count"] += 1
        for key in ("rawBytes", "gzipBytes", "brotliBytes"):
            totals[kind][key] += row[key]
    artifact_hash = digest(json.dumps(identities, separators=(",", ":")).encode())
    combined = {key: totals["javascript"][key] + totals["wasm"][key]
                for key in ("rawBytes", "gzipBytes", "brotliBytes")}
    manifests = inventory.get("manifestDigests")
    manifest_names = set(snapshot).intersection({".vite/manifest.json", "_app/version.json", "manifest.json"})
    if not isinstance(manifests, list) or len(manifests) != len(manifest_names) or not manifest_names:
        raise ValueError("manifest_set")
    seen_manifests = set()
    for row in manifests:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "rawBytes"}:
            raise ValueError("manifest_row")
        name = row["path"]
        if (not isinstance(name, str) or name not in manifest_names or name in seen_manifests
                or row["sha256"] != snapshot[name]["sha256"]
                or type(row["rawBytes"]) is not int or row["rawBytes"] != snapshot[name]["rawBytes"]):
            raise ValueError("manifest_content")
        seen_manifests.add(name)
    # Strict canonical comparison rejects bool/float stand-ins for byte counts.
    if (inventory.get("schemaVersion") != 1 or type(inventory.get("schemaVersion")) is not int
            or inventory.get("artifactIdentitySha256") != artifact_hash
            or encoded(inventory.get("totals")) != encoded(totals)
            or encoded(inventory.get("combinedJavascriptWasm")) != encoded(combined)
            or type(inventory.get("precompressedSidecarsExcluded")) is not int
            or inventory["precompressedSidecarsExcluded"] != len(snapshot) - len(expected)
            or not totals["javascript"]["count"]):
        raise ValueError("inventory_summary")


def write_receipt(path, value):
    data = encoded(value)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".perf-", delete=False) as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        temporary = stream.name
    os.replace(temporary, path)
    return digest(data)


def performance_environment(ambient, spec, validated):
    """No unchecked phase/dataset/runtime claims survive to Playwright."""
    clean = {key: value for key, value in ambient.items() if not key.startswith("OPENMATES_PERF_")}
    if spec in PERFORMANCE_SPECS:
        clean.update(validated)
    return clean


def collect(root, results, node, *, source, harness, run_id):
    """Bind existing build + served entries + exact ci-environment bytes; no network."""
    binding = {"schemaVersion": 1, "status": "unavailable", "measurementClaim": False}
    inventory = dict(binding)
    metadata = {}
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", source) or not re.fullmatch(r"[0-9a-f]{40}", harness):
            raise ValueError("identity")
        if not re.fullmatch(r"[0-9]{1,32}", str(run_id)):
            raise ValueError("identity")
        environment_path = results / "ci-environment.json"
        environment_bytes = read_regular(environment_path, 2 * 1024**2)
        environment = json.loads(environment_bytes)
        if not isinstance(environment, dict):
            raise ValueError("environment")
        frontend = environment.get("frontend", {})
        if not isinstance(frontend, dict):
            raise ValueError("frontend")
        if (environment.get("source_commit") != source or frontend.get("source_commit") != source
                or environment.get("harness_commit") != harness or str(environment.get("run_id")) != str(run_id)
                or environment.get("environment") != "github-isolated"
                or frontend.get("url") != "http://localhost:5173"
                or frontend.get("renderer") != "sveltekit-preview"):
            raise ValueError("identity")
        tool = read_regular(root / "scripts/web-production-asset-inventory.mjs", 128 * 1024)
        if digest(tool) != TOOL_SHA256:
            raise ValueError("tool")
        build = root / "frontend/apps/web_app/build"
        before = build_snapshot(build)
        entries = frontend.get("entry_asset_sha256")
        if (not isinstance(entries, dict) or not entries
                or not re.fullmatch(r"[0-9a-f]{64}", frontend.get("served_index_sha256", ""))
                or any(not re.fullmatch(r"_app/immutable/entry/[A-Za-z0-9_.-]+\.js", name)
                       or before.get(name, {}).get("sha256") != value for name, value in entries.items())):
            raise ValueError("entries")
        with tempfile.TemporaryDirectory(prefix="ci-perf-") as private:
            os.chmod(private, 0o700)
            program = Path(private) / "inventory.mjs"
            program.write_bytes(tool)
            program.chmod(0o600)
            with (Path(private) / "output.json").open("w+b") as output:
                completed = subprocess.run(
                    [node, str(program), "--client-dir", str(build), "--source-commit", source],
                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                    env={"PATH": os.defpath, "LANG": "C.UTF-8"}, timeout=120, check=False,
                )
                if completed.returncode or output.tell() > 16 * 1024**2:
                    raise ValueError("process")
                output.seek(0)
                inventory = json.load(output)
        if (not isinstance(inventory, dict) or inventory.get("status") != "available" or inventory.get("sourceCommitClaim") != source
                or not re.fullmatch(r"[0-9a-f]{64}", inventory.get("artifactIdentitySha256", ""))
                or before != build_snapshot(build)
                or environment_bytes != read_regular(environment_path, 2 * 1024**2)):
            raise ValueError("changed_or_unavailable")
        reconcile_inventory(inventory, before)
        inventory_hash = write_receipt(results / "ci-web-production-inventory.json", inventory)
        binding.update(status="bound", sourceCommit=source, harnessCommit=harness, runId=str(run_id),
                       environmentSha256=digest(environment_bytes), buildTreeSha256=digest(encoded(before)),
                       inventorySha256=inventory_hash, inventoryToolSha256=TOOL_SHA256,
                       artifactIdentitySha256=inventory["artifactIdentitySha256"],
                       servedIndexSha256=frontend["served_index_sha256"], servedEntrySha256=entries)
        metadata = {"OPENMATES_PERF_FRONTEND_MODE": "production-preview",
                    "OPENMATES_PERF_RUNTIME_SOURCE_COMMIT": source,
                    "OPENMATES_PERF_RUNTIME_ASSET_INVENTORY_SHA256": inventory_hash}
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        # No arbitrary exception text/child output/partial inventory is exported.
        inventory = {"schemaVersion": 1, "status": "unavailable", "measurementClaim": False,
                     "reason": "production_inventory_binding_unavailable"}
        binding["reason"] = "production_inventory_binding_unavailable"
        metadata = {}
        write_receipt(results / "ci-web-production-inventory.json", inventory)
    write_receipt(results / "ci-web-performance-binding.json", binding)
    return metadata
