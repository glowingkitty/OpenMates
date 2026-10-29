"""Exact isolated production-loader supplier; no release or ambient activation.

Consume the existing trusted compiler/packager once before the web build. Project
its independently verified same-job package into the existing Vite receipt shape.
The build and E2E revalidate original source, tools, locks and every package byte.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

try:
    from scripts import ci_rust_wasm as lane
    from scripts.ci_results import valid_rust_wasm_compiler_receipt
except ModuleNotFoundError:
    import ci_rust_wasm as lane
    from ci_results import valid_rust_wasm_compiler_receipt

SPEC = "rust-core-production-saved-session.spec.ts"
DESTINATION = Path("target/ci-production-rust-core")
RECEIPT_PIN = "OPENMATES_PRODUCTION_RUST_RECEIPT_SHA256"


def require_selector(ambient):
    lane.sdk.require(
        ambient.get("GITHUB_ACTIONS") == "true"
        and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and ambient.get("OPENMATES_CI_ISOLATED") == "1"
        and ambient.get("CI_TEST_MODE") == "e2e"
        and lane.production_browser_e2e_targets(
            json.loads(ambient.get("CI_SPECS_JSON", "[]"))
        )
        and not ambient.get("CI_CASE_TITLE")
        and not ambient.get("CI_CAPACITY_CONFIGURATION"),
        "admission",
    )


def verified_package(root, ambient):
    require_selector(ambient)
    source, tree = (
        lane.sdk.git(root, "rev-parse", "HEAD"),
        lane.sdk.git(root, "rev-parse", "HEAD^{tree}"),
    )
    metadata_profile = lane.metadata.targets(json.loads(ambient["CI_SPECS_JSON"]))
    first_session_profile = lane.metadata.first_session_targets(
        json.loads(ambient["CI_SPECS_JSON"])
    )
    native_recovery_profile = lane.metadata.native_recovery_targets(
        json.loads(ambient["CI_SPECS_JSON"])
    )
    activechat_profile = lane.metadata.activechat_targets(
        json.loads(ambient["CI_SPECS_JSON"])
    )
    new_chat_profile = lane.metadata.new_chat_targets(
        json.loads(ambient["CI_SPECS_JSON"])
    )
    expected = lane.source_inputs_from_git(
        root,
        source,
        metadata_profile=metadata_profile,
        first_session_profile=first_session_profile,
        native_recovery_profile=native_recovery_profile,
        activechat_profile=activechat_profile,
        new_chat_profile=new_chat_profile,
    )
    lane.sdk.require(
        source == ambient.get("BUILD_COMMIT_SHA")
        and tree == ambient.get("CI_CANDIDATE_TREE")
        and lane.source_snapshot(
            root,
            expected,
            metadata_profile=metadata_profile,
            first_session_profile=first_session_profile,
            native_recovery_profile=native_recovery_profile,
            activechat_profile=activechat_profile,
            new_chat_profile=new_chat_profile,
        )
        == expected,
        "source",
    )
    folder = root / "test-results/rust-wasm"
    receipt_bytes = lane.sdk.regular(
        root / "test-results/ci-rust-wasm.json", 2 * 1024**2
    )
    lane.sdk.require(lane.sdk.sha(receipt_bytes) == ambient.get(RECEIPT_PIN), "outputs")
    receipt = json.loads(receipt_bytes)
    lane.sdk.require(
        receipt.get("status") == "passed"
        and all(
            receipt.get(key) is True
            for key in (
                "sourceHeld",
                "cleanupVerified",
                "compilationProof",
                "packagingProof",
            )
        ),
        "packaging",
    )
    manifest_bytes = lane.sdk.regular(folder / "package-manifest.json", 2 * 1024**2)
    lane.sdk.require(
        lane.sdk.sha(manifest_bytes)
        == ambient.get("OPENMATES_BROWSER_PACKAGE_MANIFEST_SHA256"),
        "outputs",
    )
    inventory = lane.package_inventory(
        folder / "package", expected, metadata_profile=metadata_profile
    )
    files = {
        row["path"]: lane.sdk.regular(folder / "package" / row["path"])
        for row in inventory["files"]
    }
    artifact = lane.sdk.regular(folder / lane.WASM_NAME, 128 * 1024**2)
    job = {
        "source": source,
        "run_id": ambient["GITHUB_RUN_ID"],
        "mode": "e2e",
        "specs": json.dumps(json.loads(ambient["CI_SPECS_JSON"])),
    }
    lane.sdk.require(
        valid_rust_wasm_compiler_receipt(
            receipt,
            job,
            ambient["CI_HARNESS_COMMIT"],
            expected_inputs=expected,
            expected_tree=tree,
            artifact=artifact,
            package_manifest=manifest_bytes,
            package_files=files,
        ),
        "outputs",
    )
    return json.loads(manifest_bytes), expected, files


def project_receipt(root, manifest, expected, files):
    """Re-encode metadata only; each compiler-produced file remains byte-exact."""
    inputs = {}
    for crate in ("packages/openmates-rust", "packages/openmates-browser-bindings"):
        names = [crate + "/Cargo.toml", crate + "/Cargo.lock"]
        for entry in (root / crate / "src").rglob("*"):
            lane.sdk.require(not entry.is_symlink(), "source")
            if entry.is_file():
                names.append(entry.relative_to(root).as_posix())
        for name in ("build.rs", ".cargo/config", ".cargo/config.toml"):
            entry = root / crate / name
            if entry.exists() or entry.is_symlink():
                names.append(crate + "/" + name)
        for name in names:
            raw = lane.sdk.regular(root / name)
            lane.sdk.require(
                name in expected and lane.sdk.sha(raw) == expected[name], "source"
            )
            inputs[name] = {"sha256": expected[name], "bytes": len(raw)}
    # The upstream compiler rejects untracked Cargo configs; do not silently omit
    # a config that the existing plugin would otherwise see as a build input.
    lane.sdk.require(
        not any(
            (root / name).exists() or (root / name).is_symlink()
            for name in (".cargo/config", ".cargo/config.toml")
        ),
        "source",
    )
    rows = [
        {
            "path": name,
            "rawBytes": len(files[name]),
            "sha256": lane.sdk.sha(files[name]),
        }
        for name in sorted(files)
    ]
    receipt = {
        "schemaVersion": 1,
        "status": "passed",
        "target": manifest["target"],
        "toolchain": manifest["toolchain"],
        "wasmBindgenVersion": manifest["wasmBindgenVersion"],
        "inputWasmSha256": manifest["inputWasmSha256"],
        "toolSha256": manifest["toolSha256"],
        "sourceInputs": dict(sorted(inputs.items())),
        "browserExecutionVerified": False,
        "applicationActivated": False,
        "inventory": {
            "files": rows,
            "rawBytes": sum(row["rawBytes"] for row in rows),
            "inventorySha256": lane.sdk.sha(
                json.dumps(rows, separators=(",", ":")).encode()
            ),
        },
    }
    if manifest.get("features") == [lane.metadata.FEATURE]:
        lane.sdk.require(lane.metadata.EXTRA_INPUTS <= set(expected), "source")
        receipt["features"] = [lane.metadata.FEATURE]
        receipt["metadataPrototypeInputs"] = {
            name: {
                "sha256": expected[name],
                "bytes": len(lane.sdk.regular(root / name)),
            }
            for name in lane.metadata.WEB_INPUTS
        }
    return json.dumps(receipt, separators=(",", ":")).encode()


def safe_destination(root, *, fresh):
    destination = root / DESTINATION
    current = root
    for part in DESTINATION.parts:
        current /= part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            lane.sdk.require(
                stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), "outputs"
            )
    lane.sdk.require(not fresh or not destination.exists(), "outputs")
    return destination


def prepare(root, ambient):
    require_selector(ambient)
    package_env = lane.prepare_browser_e2e_package(root, environ=ambient)
    receipt_bytes = lane.sdk.regular(
        root / "test-results/ci-rust-wasm.json", 2 * 1024**2
    )
    pins = {**package_env, RECEIPT_PIN: lane.sdk.sha(receipt_bytes)}
    manifest, expected, files = verified_package(root, {**ambient, **pins})
    projected = project_receipt(root, manifest, expected, files)
    destination = safe_destination(root, fresh=True)
    destination.mkdir(mode=0o700, parents=True)
    for name, raw in files.items():
        path = destination / "pkg" / name
        parent = destination
        for part in path.relative_to(destination).parts[:-1]:
            parent /= part
            parent.mkdir(mode=0o700, exist_ok=True)
        with path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
    with (destination / "receipt.json").open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(projected)
    pins["OPENMATES_RUST_CORE_ARTIFACT"] = lane.sdk.sha(projected)
    verify_for_e2e(root, environ={**ambient, **pins})
    return pins


def verify_for_e2e(root, *, environ=None):
    ambient = os.environ if environ is None else environ
    manifest, expected, files = verified_package(root, ambient)
    projected = project_receipt(root, manifest, expected, files)
    destination = safe_destination(root, fresh=False)
    lane.sdk.require(
        lane.sdk.regular(destination / "receipt.json", 1024**2) == projected
        and lane.sdk.sha(projected) == ambient.get("OPENMATES_RUST_CORE_ARTIFACT"),
        "outputs",
    )
    # Inventory rejects additional modules, symlinks and altered exact package IO.
    lane.sdk.require(
        lane.package_inventory(
            destination / "pkg",
            expected,
            metadata_profile=lane.metadata.targets(
                json.loads(ambient["CI_SPECS_JSON"])
            ),
        )
        == lane.package_inventory(
            root / "test-results/rust-wasm/package",
            expected,
            metadata_profile=lane.metadata.targets(
                json.loads(ambient["CI_SPECS_JSON"])
            ),
        ),
        "outputs",
    )
    return {"OPENMATES_RUST_CORE_ARTIFACT": lane.sdk.sha(projected)}


def build_environment(root, ambient):
    verify_for_e2e(root, environ=ambient)
    destination = safe_destination(root, fresh=False)
    env = {
        key: value
        for key, value in ambient.items()
        if key
        not in {
            "OPENMATES_RUST_CORE_ASSETS",
            "OPENMATES_RUST_CORE_MANIFEST",
            "OPENMATES_RUST_CORE_MANIFEST_SHA256",
        }
    }
    env.update(
        OPENMATES_RUST_CORE_ASSETS="1",
        OPENMATES_RUST_CORE_MANIFEST=str(destination / "receipt.json"),
        OPENMATES_RUST_CORE_MANIFEST_SHA256=ambient["OPENMATES_RUST_CORE_ARTIFACT"],
    )
    if lane.metadata.targets(json.loads(ambient["CI_SPECS_JSON"])):
        env.update(
            OPENMATES_RUST_METADATA_PROTOTYPE="1", OPENMATES_RUST_METADATA_TESTS="1"
        )
    else:
        env.pop("OPENMATES_RUST_METADATA_PROTOTYPE", None)
        env.pop("OPENMATES_RUST_METADATA_TESTS", None)
    # No ambient prototype activation. Only this exact isolated singleton may
    # build the real Page startup path; old15 metadata profile remains literal.
    env.pop("VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE", None)
    if json.loads(ambient["CI_SPECS_JSON"]) in (
        [lane.metadata.STARTUP_SPEC],
        [lane.metadata.PAIRED_SPEC],
        [lane.metadata.FIRST_SESSION_SPEC],
        [lane.metadata.ACTIVECHAT_SPEC],
        [lane.metadata.NEW_CHAT_SPEC],
    ):
        env["VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE"] = "1"
    env.pop("OPENMATES_RUST_FIRST_SESSION_PROVIDER", None)
    if lane.metadata.first_session_targets(json.loads(ambient["CI_SPECS_JSON"])):
        env["OPENMATES_RUST_FIRST_SESSION_PROVIDER"] = "1"
    return env


def build(root, ambient):
    env = build_environment(root, ambient)
    subprocess.run(
        ["pnpm", "--dir", "frontend/apps/web_app", "exec", "vite", "build"],
        cwd=root,
        env=env,
        check=True,
        timeout=900,
    )
    verify_for_e2e(root, environ=ambient)


def main():
    lane.sdk.require(
        len(sys.argv) == 2 and sys.argv[1] in {"prepare", "build"}, "admission"
    )
    root = Path(os.environ["OPENMATES_CI_SOURCE_ROOT"])
    if sys.argv[1] == "build":
        build(root, os.environ)
    else:
        pins = prepare(root, os.environ)
        with open(os.environ["GITHUB_ENV"], "a") as stream:
            for key, value in sorted(pins.items()):
                lane.sdk.require("\n" not in value and "\r" not in value, "outputs")
                stream.write(key + "=" + value + "\n")


if __name__ == "__main__":
    main()
