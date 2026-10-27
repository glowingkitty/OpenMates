"""Trusted fixed DedicatedWorker test transport; no application or product APIs."""

from __future__ import annotations
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import time
import urllib.request

try:
    from scripts import ci_sdk_conformance as sdk
except ModuleNotFoundError:
    import ci_sdk_conformance as sdk

PLAYWRIGHT_VERSION = "1.60.0"
# Existing reviewed pnpm-lock.yaml integrity; official registry archive, no scripts.
PLAYWRIGHT_INTEGRITY = "sha512-9bW6zvX/m0lEbgTKJ6YppOKx8H3VOPBMOCFh2irXFOT4BbHgrx5hPjwJYLT40Lu+4qtD36qKc/Hn56StUW57IA=="
PLAYWRIGHT_BROWSERS_SHA256 = (
    "af53e32ffe35a024ddb34563700956b01ada00ac7e9270ba5df0604ec57e38e1"
)
CHROMIUM_REVISION = "1223"
CHROMIUM_VERSION = "148.0.7778.96"
PLAYWRIGHT_URL = (
    "https://registry.npmjs.org/playwright-core/-/playwright-core-1.60.0.tgz"
)
STAGES = (
    "worker-test-build",
    "worker-runner-version",
    "worker-chromium-install",
    "worker-dedicated-tests",
)
SECONDS = (1800, 30, 300, 300)
CLEANUP_RESERVE = 30
MAX_ARCHIVE = 32 * 1024**2
MAX_PACKAGE = 128 * 1024**2
MAX_WASM = 128 * 1024**2
REQUIRED_TESTS = (
    "cloned_nonextractable_key_preserves_nist_aes256_vector_and_never_exports",
    "extractable_key_uses_same_primitive_without_export_or_attribute_change",
    "wrong_key_tag_nonce_and_short_tag_fail_closed",
    "wrong_algorithm_length_usage_and_key_type_are_rejected",
    "capability_cancellation_denies_late_encrypt_and_decrypt_results",
    "same_material_new_capability_is_distinct_and_invalidated_old_result_cannot_publish",
    "dropped_consumer_still_wipes_real_webcrypto_plaintext_at_settlement",
    "shared_eleven_codec_cases_match_actual_webcrypto_for_both_extractability_values",
    "real_webcrypto_equals_native_rust_and_independent_vectors_without_export",
    "every_original_scope_checkpoint_refuses_before_plaintext_publication",
    "dropped_consumer_wipes_late_real_decrypt_output",
)


def commands():
    return [
        [
            "cargo",
            "+1.98.1",
            "test",
            "--locked",
            "--release",
            "--manifest-path",
            "packages/openmates-browser-bindings/Cargo.toml",
            "--target",
            "wasm32-unknown-unknown",
            "--lib",
            "--no-run",
            "--message-format=json-render-diagnostics",
        ],
        ["wasm-bindgen-test-runner", "--version"],
        [
            "node",
            ".ci-worker/playwright/package/cli.js",
            "install",
            "--no-shell",
            "chromium",
        ],
        ["node", ".ci-worker/driver.mjs"],
    ]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise sdk.Refused("worker")


def fetch_package(check, deadline):
    """One fixed TLS supplier, pinned archive integrity, bounded streaming."""
    check()
    sdk.require(time.monotonic() < deadline, "deadline")
    chunks, size = [], 0
    with urllib.request.build_opener(NoRedirect()).open(
        PLAYWRIGHT_URL, timeout=min(5, deadline - time.monotonic())
    ) as response:
        sdk.require(response.status == 200 and response.url == PLAYWRIGHT_URL, "worker")
        while True:
            check()
            sdk.require(deadline - time.monotonic() > 5, "deadline")
            raw = response.read(128 * 1024)
            if not raw:
                break
            check()
            sdk.require(time.monotonic() < deadline, "deadline")
            size += len(raw)
            sdk.require(size <= MAX_ARCHIVE, "worker")
            chunks.append(raw)
    raw = b"".join(chunks)
    sdk.require(
        "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
        == PLAYWRIGHT_INTEGRITY,
        "worker",
    )
    return raw


def extract_package(raw, destination, check):
    """No links, devices, traversal, duplicate paths, scripts or archive modes."""
    sdk.require(not destination.exists(), "worker")
    destination.mkdir(mode=0o700)
    seen, total = set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for index, entry in enumerate(archive):
            check()
            path = Path(entry.name)
            sdk.require(
                index < 4096
                and not path.is_absolute()
                and path.parts
                and path.parts[0] == "package"
                and not {"..", "."}.intersection(path.parts)
                and "\\" not in entry.name
                and entry.name not in seen
                and (entry.isdir() or entry.isfile()),
                "worker",
            )
            seen.add(entry.name)
            target = destination / path
            if entry.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            total += entry.size
            sdk.require(
                0 <= entry.size <= MAX_ARCHIVE and total <= MAX_PACKAGE, "worker"
            )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, target.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                data = source.read(entry.size + 1)
                sdk.require(len(data) == entry.size, "worker")
                output.write(data)
    metadata = json.loads(sdk.regular(destination / "package/package.json"))
    sdk.require(
        metadata.get("name") == "playwright-core"
        and metadata.get("version") == PLAYWRIGHT_VERSION
        and not metadata.get("dependencies"),
        "worker",
    )
    digest = sdk.sha(sdk.regular(destination / "package/browsers.json"))
    sdk.require(digest == PLAYWRIGHT_BROWSERS_SHA256, "worker")
    return digest


def read_uleb(raw, offset):
    value = 0
    for shift in range(0, 35, 7):
        sdk.require(offset < len(raw), "worker")
        byte = raw[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            sdk.require(value <= 0xFFFFFFFF, "worker")
            return value, offset
    raise sdk.Refused("worker")


def wasm_tests(raw):
    """Read real test exports and the official macro's DedicatedWorker section."""
    sdk.require(
        type(raw) is bytes
        and 8 < len(raw) <= MAX_WASM
        and raw[:8] == b"\0asm\x01\0\0\0",
        "worker",
    )
    offset, modes, tests, sections = 8, [], [], 0
    while offset < len(raw):
        sections += 1
        sdk.require(sections <= 4096 and raw[offset] <= 13, "worker")
        section = raw[offset]
        size, offset = read_uleb(raw, offset + 1)
        end = offset + size
        sdk.require(end <= len(raw), "worker")
        if section == 0:
            length, start = read_uleb(raw, offset)
            finish = start + length
            sdk.require(finish <= end, "worker")
            if raw[start:finish] == b"__wasm_bindgen_test_unstable":
                modes.append(raw[finish:end])
        if section == 7:
            count, cursor = read_uleb(raw, offset)
            sdk.require(count <= 100000, "worker")
            for _ in range(count):
                length, cursor = read_uleb(raw, cursor)
                finish = cursor + length
                sdk.require(finish < end and length <= 4096, "worker")
                name = raw[cursor:finish].decode("utf-8")
                cursor = finish
                kind = raw[cursor]
                _, cursor = read_uleb(raw, cursor + 1)
                if name.startswith("__wbgt_"):
                    sdk.require(
                        kind == 0 and "$" not in name and "::" in name, "worker"
                    )
                    test = name.split("::", 1)[1]
                    sdk.require(re.fullmatch(r"[A-Za-z0-9_:]{1,240}", test), "worker")
                    tests.append(test)
                    sdk.require(len(tests) <= 64, "worker")
            sdk.require(cursor == end, "worker")
        offset = end
    sdk.require(
        modes == [b"\x02"]
        and 8 <= len(tests) <= 64
        and len(tests) == len(set(tests))
        and set(REQUIRED_TESTS) <= {name.rsplit("::", 1)[-1] for name in tests},
        "worker",
    )
    return sorted(tests)


def authored_tests(work, inputs):
    """Bounded explicit macro spelling in held browser source; compile exports
    must contain every authored case. Unknown syntax fails closed for review.
    """
    names = []
    for name, digest in inputs.items():
        if not name.startswith(
            "packages/openmates-browser-bindings/src/"
        ) or not name.endswith(".rs"):
            continue
        raw = sdk.regular(work / name, 2 * 1024**2)
        sdk.require(sdk.sha(raw) == digest, "source")
        names.extend(
            re.findall(
                r"#\[wasm_bindgen_test\(async\)\]\s*async fn ([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                raw.decode(),
            )
        )
    sdk.require(
        8 <= len(names) <= 64
        and len(names) == len(set(names))
        and set(REQUIRED_TESTS) <= set(names),
        "worker",
    )
    return set(names)


def test_artifact(log, target):
    """Require exactly one Cargo test artifact in the private wasm test directory."""
    candidates = []
    for line in sdk.regular(log, sdk.MAX_LOG).decode().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (
            type(row) is dict
            and row.get("reason") == "compiler-artifact"
            and row.get("profile", {}).get("test") is True
            and row.get("target", {}).get("name") == "openmates_browser_bindings"
            and row.get("executable")
        ):
            path = Path(row["executable"])
            sdk.require(
                path.is_absolute()
                and path.resolve() == path
                and path.parent == target / "wasm32-unknown-unknown/release/deps"
                and re.fullmatch(
                    r"openmates_browser_bindings-[0-9a-f]{16}\.wasm", path.name
                ),
                "worker",
            )
            candidates.append(path)
    sdk.require(len(candidates) == 1, "worker")
    return candidates[0]


def valid_proof(proof):
    """Closed projection only; the caller executes real compiled tests first."""
    keys = {
        "schemaVersion",
        "workerRuntimeProof",
        "context",
        "requiredTests",
        "passed",
        "failed",
        "ignored",
        "filteredOut",
        "testWasmSha256",
        "controllerSha256",
        "runnerProvenance",
        "playwright",
        "cleanup",
    }
    if (
        type(proof) is not dict
        or any(type(key) is not str for key in proof)
        or set(proof) != keys
    ):
        return False
    tests = proof["requiredTests"]
    if (
        type(tests) is not list
        or not 8 <= len(tests) <= 64
        or any(
            type(v) is not str or not re.fullmatch(r"[A-Za-z0-9_:]{1,240}", v)
            for v in tests
        )
        or tests != sorted(set(tests))
        or not set(REQUIRED_TESTS) <= {v.rsplit("::", 1)[-1] for v in tests}
    ):
        return False
    if (
        type(proof["schemaVersion"]) is not int
        or proof["schemaVersion"] != 1
        or proof["workerRuntimeProof"] is not True
        or type(proof["context"]) is not str
        or proof["context"] != "dedicated-worker"
        or type(proof["passed"]) is not int
        or proof["passed"] != len(tests)
        or any(
            type(proof[k]) is not int or proof[k] != 0
            for k in ("failed", "ignored", "filteredOut")
        )
        or type(proof["cleanup"]) is not dict
        or set(proof["cleanup"])
        != {"browserClosed", "serverStopped", "serverExitCode", "serverExitSignal"}
        or proof["cleanup"]["browserClosed"] is not True
        or proof["cleanup"]["serverStopped"] is not True
        or proof["cleanup"]["serverExitCode"] is not None
        or type(proof["cleanup"]["serverExitSignal"]) is not str
        or proof["cleanup"]["serverExitSignal"] != "SIGTERM"
    ):
        return False
    if any(
        type(proof[k]) is not str or not re.fullmatch(r"[0-9a-f]{64}", proof[k])
        for k in ("testWasmSha256", "controllerSha256")
    ):
        return False
    p = proof["playwright"]
    if (
        type(p) is not dict
        or any(type(key) is not str for key in p)
        or set(p)
        != {
            "version",
            "integrity",
            "browsersSha256",
            "browserRevision",
            "browserVersion",
            "browserBinarySha256",
        }
        or any(type(value) is not str for value in p.values())
        or p["version"] != PLAYWRIGHT_VERSION
        or p["integrity"] != PLAYWRIGHT_INTEGRITY
        or p["browsersSha256"] != PLAYWRIGHT_BROWSERS_SHA256
        or p["browserRevision"] != CHROMIUM_REVISION
        or p["browserVersion"] != CHROMIUM_VERSION
        or type(p["browserRevision"]) is not str
        or not re.fullmatch(r"[0-9]{1,12}", p["browserRevision"])
        or type(p["browserVersion"]) is not str
        or not re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,6}){3}", p["browserVersion"])
        or any(
            type(p[k]) is not str or not re.fullmatch(r"[0-9a-f]{64}", p[k])
            for k in ("browsersSha256", "browserBinarySha256")
        )
    ):
        return False
    provenance = proof["runnerProvenance"]
    keys = {
        "package",
        "version",
        "registry",
        "url",
        "crateSha256",
        "publishedCargoLockSha256",
        "binarySha256",
        "binaryIdentity",
    }
    if (
        type(provenance) is not dict
        or any(type(key) is not str for key in provenance)
        or set(provenance) != keys
    ):
        return False
    if any(type(provenance[key]) is not str for key in keys - {"binaryIdentity"}):
        return False
    identity = provenance["binaryIdentity"]
    if (
        type(identity) is not dict
        or set(identity)
        != {"device", "inode", "bytes", "mtimeNs", "ctimeNs", "mode", "uid", "links"}
        or any(
            type(value) is not int or not 0 <= value <= 2**63 - 1
            for value in identity.values()
        )
        or identity["links"] != 1
        or not 0 < identity["bytes"] <= 64 * 1024**2
        or not stat.S_ISREG(identity["mode"])
        or not identity["mode"] & 0o111
        or identity["mode"] & 0o002
    ):
        return False
    return (
        type(proof["schemaVersion"]) is int
        and proof["controllerSha256"]
        == sdk.sha(sdk.regular(Path(__file__).with_suffix(".mjs"), 256 * 1024))
        and provenance["package"] == "wasm-bindgen-cli"
        and provenance["version"] == "0.2.129"
        and provenance["registry"] == "crates.io"
        and provenance["url"] == "https://crates.io/crates/wasm-bindgen-cli/0.2.129"
        and provenance["crateSha256"]
        == "5fd044ed178958a277eeaf21f3d384287b0f4428d38c019141df01da9c03168c"
        and all(
            type(provenance[key]) is str
            and re.fullmatch(r"[0-9a-f]{64}", provenance[key])
            for key in ("crateSha256", "publishedCargoLockSha256", "binarySha256")
        )
    )


def execute(
    runner,
    private,
    work,
    node,
    verify_node,
    inputs,
    detach,
    provenance_reader,
    controller_bytes,
):
    """Actual compile -> official manual runner -> actual Playwright worker test."""
    sdk.require(
        callable(verify_node) and type(node) is str and Path(node).is_absolute(),
        "worker",
    )
    deadline = runner.deadline - CLEANUP_RESERVE

    def check():
        runner.check()
        sdk.require(time.monotonic() < deadline, "deadline")

    def held():
        check()
        sdk.require(
            all(
                sdk.sha(sdk.regular(work / name)) == digest
                for name, digest in inputs.items()
            ),
            "source",
        )

    def step(index):
        held()
        verify_node()
        seconds = min(SECONDS[index], deadline - time.monotonic())
        sdk.require(seconds > 0, "deadline")
        result = runner.run(STAGES[index], commands()[index], seconds=seconds)
        held()
        verify_node()
        return result

    folder = work / ".ci-worker"
    folder.mkdir(mode=0o700)
    runner.env["PATH"] = str(Path(node).parent) + os.pathsep + runner.env["PATH"]
    build_log = step(0)
    artifact = test_artifact(build_log, private / "target")
    identity = sdk.file_identity(artifact.lstat())
    raw = sdk.regular(artifact, MAX_WASM)
    required = wasm_tests(raw)
    sdk.require(
        {name.rsplit("::", 1)[-1] for name in required} == authored_tests(work, inputs),
        "worker",
    )
    sdk.require(identity == sdk.file_identity(artifact.lstat()), "source")
    test_file = folder / "tests.wasm"
    test_file.write_bytes(raw)
    test_file.chmod(0o600)
    detach(work, runner.deadline, binary_name="wasm-bindgen-test-runner")
    provenance = provenance_reader(
        private, work, binary_name="wasm-bindgen-test-runner"
    )
    version = step(1)
    sdk.require(
        sdk.regular(version, 65536).decode().strip()
        == "wasm-bindgen-test-runner 0.2.129",
        "worker",
    )
    sdk.require(
        runner.steps[-1]["command"]["executableSha256"] == provenance["binarySha256"],
        "worker",
    )
    archive = fetch_package(check, deadline)
    browsers_hash = extract_package(archive, folder / "playwright", check)
    browser_doc = json.loads(sdk.regular(folder / "playwright/package/browsers.json"))
    candidates = [
        row for row in browser_doc["browsers"] if row.get("name") == "chromium"
    ]
    sdk.require(
        len(candidates) == 1
        and candidates[0].get("revision") == CHROMIUM_REVISION
        and candidates[0].get("browserVersion") == CHROMIUM_VERSION
        and type(candidates[0].get("revision")) is str
        and re.fullmatch(r"[0-9]{1,12}", candidates[0]["revision"])
        and type(candidates[0].get("browserVersion")) is str
        and re.fullmatch(
            r"[0-9]{1,4}(?:\.[0-9]{1,6}){3}", candidates[0]["browserVersion"]
        ),
        "worker",
    )
    runner.env["PLAYWRIGHT_BROWSERS_PATH"] = str(folder / "browsers")
    step(2)
    driver = Path(__file__).with_suffix(".mjs")
    sdk.require(
        type(controller_bytes) is bytes and 0 < len(controller_bytes) <= 256 * 1024,
        "worker",
    )
    driver_raw = controller_bytes
    sdk.require(sdk.regular(driver, 256 * 1024) == driver_raw, "source")
    controller_hash = sdk.sha(driver_raw)
    (folder / "driver.mjs").write_bytes(driver_raw)
    (folder / "driver.mjs").chmod(0o600)
    timeout = int(min(SECONDS[3], deadline - time.monotonic()) * 1000)
    sdk.require(timeout > 0, "deadline")
    sdk.write(
        folder / "request.json",
        {
            "requiredTests": required,
            "testWasmSha256": sdk.sha(raw),
            "runnerSha256": provenance["binarySha256"],
            "browserVersion": candidates[0]["browserVersion"],
            "timeoutMs": timeout,
        },
    )
    log = step(3)

    def unique(pairs):
        value = {}
        for key, item in pairs:
            sdk.require(key not in value, "worker")
            value[key] = item
        return value

    result = json.loads(sdk.regular(log, 65536), object_pairs_hook=unique)
    sdk.require(
        type(result) is dict
        and set(result)
        == {
            "passed",
            "failed",
            "ignored",
            "filteredOut",
            "browserBinarySha256",
            "context",
            "cleanup",
        },
        "worker",
    )
    proof = {
        "schemaVersion": 1,
        "workerRuntimeProof": True,
        "requiredTests": required,
        "testWasmSha256": sdk.sha(raw),
        "controllerSha256": controller_hash,
        "runnerProvenance": provenance,
        "playwright": {
            "version": PLAYWRIGHT_VERSION,
            "integrity": PLAYWRIGHT_INTEGRITY,
            "browsersSha256": browsers_hash,
            "browserRevision": candidates[0]["revision"],
            "browserVersion": candidates[0]["browserVersion"],
            "browserBinarySha256": result.pop("browserBinarySha256"),
        },
        **result,
    }
    sdk.require(
        valid_proof(proof)
        and sdk.sha(sdk.regular(driver, 256 * 1024)) == controller_hash
        and sdk.sha(sdk.regular(folder / "driver.mjs", 256 * 1024)) == controller_hash
        and provenance_reader(private, work, binary_name="wasm-bindgen-test-runner")
        == provenance,
        "worker",
    )
    held()
    return proof
