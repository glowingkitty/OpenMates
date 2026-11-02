"""Fixed genuine Rust/npm/Python execution gate. Run only in isolated CI."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
_PACKAGED_PROBE = None
if os.environ.get("OPENMATES_SDK_V1_PACKAGE_CONSUMER") is not None:
    try:
        import importlib.util

        _probe_spec = importlib.util.spec_from_file_location(
            "fixed_packaged_native23_probe", ROOT / "scripts/check_packaged_sdk_v1.py"
        )
        _probe_module = importlib.util.module_from_spec(_probe_spec)
        _probe_spec.loader.exec_module(_probe_module)
        _PACKAGED_PROBE = _probe_module._native23_probe_from_environment(ROOT)
    except Exception:
        pass


def _probe_mark(site, case=None):
    try:
        if _PACKAGED_PROBE is not None:
            _PACKAGED_PROBE.mark(site, case)
    except Exception:
        pass


def _probe_child(result):
    try:
        if _PACKAGED_PROBE is not None:
            _PACKAGED_PROBE.child(result)
    except Exception:
        pass


def _probe_failed(error):
    try:
        if _PACKAGED_PROBE is not None:
            _PACKAGED_PROBE.failed(error)
    except Exception:
        pass


_probe_mark("runner_import")
try:
    from api_key_foundation_peer import ApiKeyFoundationPeer
except Exception as _probe_import_error:
    _probe_failed(_probe_import_error)
    raise


def main():
    _probe_mark("arguments")
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["rust", "npm", "python"], required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument(
        "--capability", default="sdk.configuration", choices=["sdk.configuration"]
    )
    args = parser.parse_args()
    fixture = ROOT / "tests/sdk-conformance/fixtures/api-key-foundation.json"
    if args.fixture is not None:
        assert args.fixture.resolve() == fixture.resolve(), (
            "fixed reviewed fixture only"
        )
    _probe_mark("fixture")
    suite = json.loads(fixture.read_text())["capabilities"]["sdk.configuration"]
    identity = {"rust": "rust", "npm": "npm", "python": "pip"}[args.language]
    commands = {
        "rust": [
            "cargo",
            "run",
            "--locked",
            "--manifest-path",
            str(ROOT / "packages/openmates-session-bindings/Cargo.toml"),
            "--example",
            "api-key-foundation-conformance",
            "--",
        ],
        "npm": [
            "node",
            str(ROOT / "tests/sdk-conformance/runners/api-key-foundation.mjs"),
        ],
        "python": [
            sys.executable,
            str(ROOT / "tests/sdk-conformance/runners/api_key_foundation_case.py"),
        ],
    }
    results = []
    for vector in suite["vectors"]:
        _probe_mark("peer_start", vector["id"])
        peer = ApiKeyFoundationPeer(suite, vector, identity).start()
        try:
            # No missing-native/env skip, fixture simulation or fallback command.
            _probe_mark("adapter_launch", vector["id"])
            result = subprocess.run(
                commands[args.language] + [str(fixture), vector["id"], peer.endpoint],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120,
                env=os.environ.copy(),
            )
            _probe_child(result)
            assert result.returncode == 0, (
                "genuine adapter executable failed: " + result.stderr[-1800:]
            )
            _probe_mark("result_decode", vector["id"])
            actual = json.loads(result.stdout)
            _probe_mark("result_identity", vector["id"])
            assert (
                actual["id"] == vector["id"]
                and actual["adapter"] == "actual-rust-api-key-library"
            )
            _probe_mark("value_assertions", vector["id"])
            if "expected_error" in vector:
                assert (
                    actual.get("error") == vector["expected_error"]
                    and "value" not in actual
                )
            else:
                assert (
                    actual.get("value") == vector["expected"] and "error" not in actual
                )
            assert "synthetic-private-server-diagnostic" not in result.stdout
            _probe_mark("wire_assertions", vector["id"])
            wire = peer.status()
            assert wire["failure"] is None
            for key in ["skill_posts", "account_reads", "downloads", "retention_posts"]:
                assert wire[key] == vector.get("expected_" + key, 0), (
                    vector["id"],
                    key,
                    wire,
                )
            assert wire["auth"] == 0, (
                "API-key path must not fabricate Cookie session validation"
            )
            if vector["mode"] == "task_array_order":
                # Frozen peer returns A pending once. Assert exact original-ID
                # counts, not impossible [A,B] or a serial transport schedule.
                assert wire["polls"] == {"task_a": 2, "task_b": 1}
                assert len(wire["poll_order"]) == 3 and set(wire["poll_order"]) == {
                    "task_a",
                    "task_b",
                }
            if vector["mode"] == "cancel_after_dispatch":
                assert wire["polls"] == {}, "cancel original task before polling"
            if vector["mode"] in {
                "parallel_code_success",
                "parallel_code_failed_status",
                "parallel_code_http_failure",
            }:
                assert (
                    wire["code_all_arrived"]
                    and wire["code_a_headers_sent"]
                    and wire["code_b_sent"]
                    and wire["code_release_verified"]
                )
                assert wire["polls"] == {job: 1 for job in vector["original_code_ids"]}
                assert len(wire["poll_order"]) == 4 and set(wire["poll_order"]) == set(
                    vector["original_code_ids"]
                )
                if vector["mode"] == "parallel_code_http_failure":
                    assert wire["code_terminal"], "typed HTTP failure before A release"
            if vector["mode"] in {"parallel_tasks_success", "parallel_tasks_failure"}:
                assert (
                    wire["parallel_all_arrived"]
                    and wire["parallel_a_headers_sent"]
                    and wire["parallel_b_sent"]
                    and wire["parallel_release_verified"]
                )
                assert wire["polls"] == {
                    task: 1 for task in vector["original_task_ids"]
                }, "one GET per original ID; no retries or replacements"
                assert set(wire["poll_order"]) == set(vector["original_task_ids"])
                if vector["mode"] == "parallel_tasks_failure":
                    assert wire["parallel_terminal"], (
                        "caller typed failure before A release"
                    )
            if vector["mode"].startswith(("task_ids_one_", "task_id_direct_")):
                assert wire["polls"] == {"task_one": 1}
            results.append(
                {
                    "id": vector["id"],
                    "status": "passed",
                    "adapter": actual["adapter"],
                    "peer": wire,
                }
            )
        except Exception as error:
            _probe_failed(error)
            raise
        finally:
            _probe_mark("peer_cleanup", vector["id"])
            peer.stop()
        _probe_mark("case_complete", vector["id"])
    assert len(results) == 23 and len({v["id"] for v in results}) == 23
    _probe_mark("complete")
    print(
        json.dumps(
            {
                "capability": suite["capability"],
                "language": args.language,
                "status": "passed",
                "fixtureSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        _probe_failed(error)
        raise
