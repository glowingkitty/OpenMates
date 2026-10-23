# contract-test-file: tooling
"""Inert production binding tests; no app, browser, network, build or Docker."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ci_web_performance as runtime


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / "subject"
    results = root / "test-results"
    results.mkdir(parents=True)
    build = root / "frontend/apps/web_app/build"
    entry = build / "_app/immutable/entry/start.synthetic.js"
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"synthetic public javascript")
    (build / "_app/version.json").write_text('{"version":"synthetic"}')
    (build / "module.wasm").write_bytes(b"synthetic wasm")
    (build / "module.wasm.gz").write_bytes(b"synthetic gzip sidecar")
    (build / "module.wasm.br").write_bytes(b"synthetic brotli sidecar")
    tool = root / "scripts/web-production-asset-inventory.mjs"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"synthetic reviewed inventory program")
    monkeypatch.setattr(runtime, "TOOL_SHA256", runtime.digest(tool.read_bytes()))
    environment = {
        "source_commit": "a" * 40, "harness_commit": "b" * 40, "run_id": "123",
        "environment": "github-isolated", "private_ignored_value": "DO_NOT_EXPORT_SYNTHETIC",
        "frontend": {"source_commit": "a" * 40, "url": "http://localhost:5173",
                     "renderer": "sveltekit-preview", "served_index_sha256": "c" * 64,
                     "entry_asset_sha256": {entry.relative_to(build).as_posix(): runtime.digest(entry.read_bytes())}},
    }
    environment_path = results / "ci-environment.json"
    environment_path.write_text(json.dumps(environment))
    rows = []
    for name, kind in [("_app/immutable/entry/start.synthetic.js", "javascript"),
                       ("_app/version.json", "other"), ("module.wasm", "wasm")]:
        data = (build / name).read_bytes()
        rows.append({"path": name, "kind": kind, "sha256": runtime.digest(data),
                     "rawBytes": len(data), "gzipBytes": 9, "brotliBytes": 8})
    totals = {row["kind"]: {"count": 1, "rawBytes": row["rawBytes"],
                            "gzipBytes": 9, "brotliBytes": 8} for row in rows}
    manifest_data = (build / "_app/version.json").read_bytes()
    inv = {"schemaVersion": 1, "status": "available", "sourceCommitClaim": "a" * 40,
           "assets": rows, "totals": totals,
           "combinedJavascriptWasm": {"rawBytes": len(entry.read_bytes()) + len(b"synthetic wasm"),
                                      "gzipBytes": 18, "brotliBytes": 16},
           "precompressedSidecarsExcluded": 2,
           "manifestDigests": [{"path": "_app/version.json", "sha256": runtime.digest(manifest_data),
                                "rawBytes": len(manifest_data)}],
           "artifactIdentitySha256": runtime.digest(json.dumps(
               [{"path": row["path"], "sha256": row["sha256"]} for row in rows],
               separators=(",", ":")).encode())}

    def child(command, **kwargs):
        assert command[0] == "/synthetic/attested-node"
        assert Path(command[1]).read_bytes() == tool.read_bytes()
        assert Path(command[1]).stat().st_mode & 0o777 == 0o600
        assert Path(command[1]).parent.stat().st_mode & 0o777 == 0o700
        assert command[2:] == ["--client-dir", str(build), "--source-commit", "a" * 40]
        assert kwargs["env"] == {"PATH": runtime.os.defpath, "LANG": "C.UTF-8"}
        assert kwargs["stderr"] == runtime.subprocess.DEVNULL and kwargs["timeout"] == 120
        kwargs["stdout"].write(json.dumps(inv).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", child)
    return SimpleNamespace(root=root, results=results, build=build, entry=entry,
                           tool=tool, environment=environment, environment_path=environment_path,
                           child=child, inventory=inv)


def collect(f):
    return runtime.collect(f.root, f.results, "/synthetic/attested-node",
                           source="a" * 40, harness="b" * 40, run_id="123")


def unavailable(f):
    assert collect(f) == {}
    binding = json.loads((f.results / "ci-web-performance-binding.json").read_bytes())
    assert binding == {"schemaVersion": 1, "status": "unavailable", "measurementClaim": False,
                       "reason": "production_inventory_binding_unavailable"}
    assert b"DO_NOT_EXPORT_SYNTHETIC" not in (f.results / "ci-web-production-inventory.json").read_bytes()


def test_success_binds_exact_build_environment_and_inventory(fixture):
    f = fixture
    metadata = collect(f)
    inventory_path = f.results / "ci-web-production-inventory.json"
    binding = json.loads((f.results / "ci-web-performance-binding.json").read_bytes())
    assert metadata == {"OPENMATES_PERF_FRONTEND_MODE": "production-preview",
                        "OPENMATES_PERF_RUNTIME_SOURCE_COMMIT": "a" * 40,
                        "OPENMATES_PERF_RUNTIME_ASSET_INVENTORY_SHA256": hashlib.sha256(inventory_path.read_bytes()).hexdigest()}
    assert binding["status"] == "bound"
    assert binding["environmentSha256"] == runtime.digest(f.environment_path.read_bytes())
    assert binding["buildTreeSha256"] == runtime.digest(runtime.encoded(runtime.build_snapshot(f.build)))
    assert binding["inventorySha256"] == metadata["OPENMATES_PERF_RUNTIME_ASSET_INVENTORY_SHA256"]
    assert b"DO_NOT_EXPORT_SYNTHETIC" not in json.dumps(binding).encode()
    for name in ("ci-web-production-inventory.json", "ci-web-performance-binding.json"):
        assert (f.results / name).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("field,value", [("source_commit", "e" * 40), ("harness_commit", "e" * 40),
                                         ("run_id", "456"), ("environment", "development")])
def test_source_and_ci_identity_mismatch_refused(fixture, field, value):
    fixture.environment[field] = value
    fixture.environment_path.write_text(json.dumps(fixture.environment))
    unavailable(fixture)


@pytest.mark.parametrize("renderer", ["vite-dev", "unknown"])
def test_dev_resources_never_gain_production_binding(fixture, renderer):
    fixture.environment["frontend"]["renderer"] = renderer
    fixture.environment_path.write_text(json.dumps(fixture.environment))
    unavailable(fixture)


def test_wrong_served_entry_refused(fixture):
    fixture.entry.write_bytes(b"different from served bytes")
    unavailable(fixture)


def test_changed_tool_never_executed(fixture, monkeypatch):
    fixture.tool.write_bytes(b"DO_NOT_EXPORT_SYNTHETIC")
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: pytest.fail("unchecked tool executed"))
    unavailable(fixture)


def test_missing_build_unavailable(fixture):
    fixture.entry.unlink()
    unavailable(fixture)


def test_symlink_asset_refused(fixture):
    (fixture.build / "secret.js").symlink_to(fixture.environment_path)
    unavailable(fixture)


@pytest.mark.parametrize("changed", ["build", "environment"])
def test_changes_during_inventory_discard_receipt(fixture, monkeypatch, changed):
    def child(*args, **kwargs):
        result = fixture.child(*args, **kwargs)
        if changed == "build":
            fixture.entry.write_bytes(b"changed")
        else:
            fixture.environment_path.write_text("{}")
        return result
    monkeypatch.setattr(runtime.subprocess, "run", child)
    unavailable(fixture)


def test_process_failure_does_not_leak_child_details(fixture, monkeypatch):
    def child(*args, **kwargs):
        raise runtime.subprocess.TimeoutExpired("DO_NOT_EXPORT_SYNTHETIC", 120)
    monkeypatch.setattr(runtime.subprocess, "run", child)
    unavailable(fixture)


def test_ambient_claims_stripped_and_only_exact_specs_receive_verified_fields():
    ambient = {"PATH": "/synthetic", "OPENMATES_PERF_PHASE": "before",
               "OPENMATES_PERF_FIXTURE_DATA_SHA256": "e" * 64,
               "OPENMATES_PERF_RUNTIME_SOURCE_COMMIT": "f" * 40}
    verified = {"OPENMATES_PERF_RUNTIME_SOURCE_COMMIT": "a" * 40}
    for spec in runtime.PERFORMANCE_SPECS:
        assert runtime.performance_environment(ambient, spec, verified) == {"PATH": "/synthetic", **verified}
    for spec in ("nested/page-load-performance.spec.ts", "page-load-performance-extra.spec.ts", "unrelated.spec.ts"):
        assert runtime.performance_environment(ambient, spec, verified) == {"PATH": "/synthetic"}


@pytest.mark.parametrize("mode", ["file", "tree"])
def test_actual_fifo_refused_without_waiting_for_writer(tmp_path, mode):
    build = tmp_path / "build"
    build.mkdir()
    fifo = build / "waiting.js"
    os.mkfifo(fifo, 0o600)
    program = """
import sys
from pathlib import Path
from scripts.ci_web_performance import read_regular, build_snapshot
try:
    (lambda: read_regular(Path(sys.argv[1]), 1024))() if sys.argv[2] == 'file' else build_snapshot(Path(sys.argv[1]).parent)
except ValueError:
    print('special_file_refused')
else:
    raise SystemExit(1)
"""
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(runtime.__file__).parents[1])}
    result = subprocess.run([sys.executable, "-c", program, str(fifo), mode],
                            env=env, capture_output=True, text=True, timeout=2, check=True)
    assert result.stdout == "special_file_refused\n"
    assert not result.stderr


@pytest.mark.parametrize("fault", ["missing_asset", "extra_asset", "duplicate_asset", "wrong_hash", "wrong_raw",
                                    "wrong_kind", "manifest_hash", "manifest_raw", "missing_manifest",
                                    "sidecar_count", "totals", "combined", "artifact_digest", "bool_bytes"])
def test_inventory_must_reconcile_every_snapshot_record(fixture, fault):
    inv = fixture.inventory
    if fault == "missing_asset":
        inv["assets"].pop()
    elif fault == "extra_asset":
        inv["assets"].append({**inv["assets"][0], "path": "extra.js"})
    elif fault == "duplicate_asset":
        inv["assets"][1] = inv["assets"][0]
    elif fault == "wrong_hash":
        inv["assets"][0]["sha256"] = "f" * 64
    elif fault == "wrong_raw":
        inv["assets"][0]["rawBytes"] += 1
    elif fault == "wrong_kind":
        inv["assets"][0]["kind"] = "other"
    elif fault == "manifest_hash":
        inv["manifestDigests"][0]["sha256"] = "f" * 64
    elif fault == "manifest_raw":
        inv["manifestDigests"][0]["rawBytes"] += 1
    elif fault == "missing_manifest":
        inv["manifestDigests"].clear()
    elif fault == "sidecar_count":
        inv["precompressedSidecarsExcluded"] -= 1
    elif fault == "totals":
        inv["totals"]["javascript"]["rawBytes"] += 1
    elif fault == "combined":
        inv["combinedJavascriptWasm"]["gzipBytes"] += 1
    elif fault == "artifact_digest":
        inv["artifactIdentitySha256"] = "f" * 64
    elif fault == "bool_bytes":
        inv["assets"][0]["gzipBytes"] = True
    unavailable(fixture)


def test_transient_alternate_build_restored_before_post_snapshot_is_refused(fixture, monkeypatch):
    original = fixture.entry.read_bytes()

    def child(*args, **kwargs):
        try:
            fixture.entry.write_bytes(b"transient alternate bytes")
            row = fixture.inventory["assets"][0]
            row["sha256"] = runtime.digest(fixture.entry.read_bytes())
            row["rawBytes"] = len(fixture.entry.read_bytes())
            fixture.inventory["artifactIdentitySha256"] = runtime.digest(json.dumps(
                [{"path": row["path"], "sha256": row["sha256"]} for row in fixture.inventory["assets"]],
                separators=(",", ":")).encode())
            return fixture.child(*args, **kwargs)
        finally:
            fixture.entry.write_bytes(original)
    monkeypatch.setattr(runtime.subprocess, "run", child)
    unavailable(fixture)
    assert fixture.entry.read_bytes() == original
