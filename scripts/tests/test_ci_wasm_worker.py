"""Pure closed-parser/source/provenance tests. Never install/build/run a browser."""

# contract-test-file: tooling
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import patch
import pytest

C = Path(__file__).resolve().parents[2]
# Canonical helper dependencies are read-only; the subject is the private module.
sys.path.insert(0, str(C))
SUBJECT = Path(__file__).resolve().parents[1] / "ci_wasm_worker.py"
spec = importlib.util.spec_from_file_location("scripts.ci_wasm_worker", SUBJECT)
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


def uleb(value):
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def section(kind, data):
    return bytes([kind]) + uleb(len(data)) + data


def wasm(mode=b"\x02", names=None, ignored=False):
    names = list(worker.REQUIRED_TESTS) if names is None else names
    custom = b"__wasm_bindgen_test_unstable"
    exports = bytearray(uleb(len(names)))
    for index, name in enumerate(names):
        value = (
            "__wbgt_"
            + ("$" if ignored else "0")
            + "_openmates_browser_bindings::browser::browser_crypto_tests::"
            + name
        ).encode()
        exports.extend(uleb(len(value)) + value + b"\x00" + uleb(index))
    return (
        b"\0asm\x01\0\0\0"
        + section(0, uleb(len(custom)) + custom + mode)
        + section(7, exports)
    )


def proof():
    return {
        "schemaVersion": 1,
        "workerRuntimeProof": True,
        "context": "dedicated-worker",
        "requiredTests": sorted(
            "browser::browser_crypto_tests::" + n for n in worker.REQUIRED_TESTS
        ),
        "passed": len(worker.REQUIRED_TESTS),
        "failed": 0,
        "ignored": 0,
        "filteredOut": 0,
        "testWasmSha256": "1" * 64,
        "controllerSha256": worker.sdk.sha(
            worker.sdk.regular(SUBJECT.with_suffix(".mjs"))
        ),
        "runnerProvenance": {
            "package": "wasm-bindgen-cli",
            "version": "0.2.129",
            "registry": "crates.io",
            "url": "https://crates.io/crates/wasm-bindgen-cli/0.2.129",
            "crateSha256": "5fd044ed178958a277eeaf21f3d384287b0f4428d38c019141df01da9c03168c",
            "publishedCargoLockSha256": "2" * 64,
            "binarySha256": "3" * 64,
            "binaryIdentity": {
                "device": 1,
                "inode": 1,
                "bytes": 100,
                "mtimeNs": 1,
                "ctimeNs": 1,
                "mode": 0o100700,
                "uid": 1000,
                "links": 1,
            },
        },
        "playwright": {
            "version": worker.PLAYWRIGHT_VERSION,
            "integrity": worker.PLAYWRIGHT_INTEGRITY,
            "browsersSha256": worker.PLAYWRIGHT_BROWSERS_SHA256,
            "browserRevision": worker.CHROMIUM_REVISION,
            "browserVersion": worker.CHROMIUM_VERSION,
            "browserBinarySha256": "4" * 64,
        },
        "cleanup": {
            "browserClosed": True,
            "serverStopped": True,
            "serverExitCode": None,
            "serverExitSignal": "SIGTERM",
        },
    }


def test_real_compiler_export_inventory_requires_dedicated_worker_and_all_authored_cases():
    actual = worker.wasm_tests(wasm())
    assert len(actual) == len(worker.REQUIRED_TESTS)
    assert (
        len(
            worker.wasm_tests(
                wasm(names=[*worker.REQUIRED_TESTS, "future_ninth_handoff"])
            )
        )
        == len(worker.REQUIRED_TESTS) + 1
    )
    for raw in [
        wasm(mode=b"\x01"),
        wasm(mode=b"\x05"),
        wasm(mode=b"\x02\x01"),
        wasm(names=[]),
        wasm(names=worker.REQUIRED_TESTS[:-1]),
        wasm(names=[*worker.REQUIRED_TESTS, worker.REQUIRED_TESTS[0]]),
        wasm(ignored=True),
        wasm()[:-1],
        b"\0asm\x01\0\0\0\x00\xff\xff\xff\xff\xff\xff",
    ]:
        with pytest.raises(worker.sdk.Refused):
            worker.wasm_tests(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workerRuntimeProof", False),
        ("context", "node"),
        ("passed", 0),
        ("failed", 1),
        ("ignored", 1),
        ("filteredOut", 1),
        ("schemaVersion", True),
        ("controllerSha256", "9" * 64),
    ],
)
def test_closed_proof_refuses_mock_success_shortcuts_and_wrong_producer(field, value):
    value_proof = proof()
    assert worker.valid_proof(value_proof)
    value_proof[field] = value
    assert not worker.valid_proof(value_proof)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "0.2.128"),
        ("registry", "private-registry"),
        ("url", "https://private.invalid/secret"),
        ("crateSha256", "9" * 64),
        ("binaryIdentity", {"links": 1}),
        ("raw", "PRIVATE-RAW-ERROR"),
    ],
)
def test_supplier_provenance_and_raw_fields_cannot_be_forged(field, value):
    p = proof()
    p["runnerProvenance"][field] = value
    assert not worker.valid_proof(p)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "latest"),
        ("integrity", "learned-from-download"),
        ("browserRevision", "9999"),
        ("browserVersion", "156.0.8078.47"),
        ("browsersSha256", "9" * 64),
        ("raw", "PRIVATE-RAW"),
    ],
)
def test_browser_supplier_is_the_existing_pinned_playwright_transport(field, value):
    p = proof()
    p["playwright"][field] = value
    assert not worker.valid_proof(p)


class Getter:
    def __getattribute__(self, _):
        raise AssertionError("getter must not run")

    def __eq__(self, _):
        raise AssertionError("equality must not run")


def test_malformed_objects_getters_private_paths_and_cleanup_fail_closed():
    assert not worker.valid_proof(Getter())
    for field in [
        "schemaVersion",
        "context",
        "requiredTests",
        "runnerProvenance",
        "playwright",
        "cleanup",
    ]:
        p = proof()
        p[field] = Getter()
        assert not worker.valid_proof(p)
    for field in ["version", "browserVersion", "browserRevision"]:
        p = proof()
        p["playwright"][field] = Getter()
        assert not worker.valid_proof(p)
    p = proof()
    p["runnerProvenance"]["binaryIdentity"] = Getter()
    assert not worker.valid_proof(p)
    p = proof()
    p["cleanup"]["browserClosed"] = 1
    assert not worker.valid_proof(p)
    p = proof()
    p["cleanup"]["serverExitSignal"] = "SIGKILL"
    assert not worker.valid_proof(p)
    p = proof()
    p["raw"] = "/private/secret"
    assert not worker.valid_proof(p)


def test_cargo_artifact_path_must_be_exact_private_test_module(tmp_path):
    target = tmp_path / "target"
    folder = target / "wasm32-unknown-unknown/release/deps"
    folder.mkdir(parents=True)
    good = folder / ("openmates_browser_bindings-" + "a" * 16 + ".wasm")
    good.write_bytes(wasm())
    log = tmp_path / "build.log"

    def row(path):
        return {
            "reason": "compiler-artifact",
            "profile": {"test": True},
            "target": {"name": "openmates_browser_bindings"},
            "executable": str(path),
        }

    log.write_text(json.dumps(row(good)) + "\n")
    assert worker.test_artifact(log, target) == good
    for rows in [[row(tmp_path / "private-secret.wasm")], [row(good), row(good)]]:
        log.write_text("\n".join(json.dumps(r) for r in rows))
        with pytest.raises(worker.sdk.Refused):
            worker.test_artifact(log, target)
    link = folder / ("openmates_browser_bindings-" + "b" * 16 + ".wasm")
    link.symlink_to(good)
    log.write_text(json.dumps(row(link)))
    with pytest.raises(worker.sdk.Refused):
        worker.test_artifact(log, target)


def archive(entries):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        for name, data, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.type = kind
            if kind == tarfile.SYMTYPE:
                entry.linkname = "/private/secret"
            t.addfile(entry, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return out.getvalue()


@pytest.mark.parametrize(
    "bad",
    [
        ("../escape", b"x", tarfile.REGTYPE),
        ("/private/escape", b"x", tarfile.REGTYPE),
        ("package/secret", b"", tarfile.SYMTYPE),
        ("package/secret", b"", tarfile.LNKTYPE),
    ],
)
def test_package_extraction_never_adopts_links_or_path_escape(tmp_path, bad):
    with pytest.raises(worker.sdk.Refused):
        worker.extract_package(archive([bad]), tmp_path / "supplier", lambda: None)
    assert not (tmp_path / "escape").exists()


def test_registry_fetch_checks_pinned_integrity_without_executing_anything():
    class Response(io.BytesIO):
        status = 200
        url = worker.PLAYWRIGHT_URL

    opener = SimpleNamespace(open=lambda *_a, **_kw: Response(b"unreviewed bytes"))
    with patch.object(worker.urllib.request, "build_opener", return_value=opener):
        with pytest.raises(worker.sdk.Refused):
            worker.fetch_package(lambda: None, worker.time.monotonic() + 20)


def test_budget_and_commands_preserve_locked_no_filter_execution_and_cleanup_reserve():
    assert worker.CLEANUP_RESERVE == 30
    assert worker.commands()[0][2:] == [
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
    ]
    assert not {"--ignored", "--skip", "--exact", "--no-default-features"}.intersection(
        sum(worker.commands(), [])
    )
    assert worker.commands()[2][-3:] == ["install", "--no-shell", "chromium"]


def test_all_source_authored_tests_must_be_held_and_compiled(tmp_path):
    path = "packages/openmates-browser-bindings/src/browser_crypto_tests.rs"
    file = tmp_path / path
    file.parent.mkdir(parents=True)
    text = "\n".join(
        "#[wasm_bindgen_test(async)]\nasync fn " + name + "() {}"
        for name in worker.REQUIRED_TESTS
    )
    file.write_text(text)
    inputs = {path: worker.sdk.sha(file.read_bytes())}
    assert worker.authored_tests(tmp_path, inputs) == set(worker.REQUIRED_TESTS)
    file.write_text(
        text + "\n#[wasm_bindgen_test(async)]\nasync fn future_ninth_handoff() {}"
    )
    with pytest.raises(worker.sdk.Refused):
        worker.authored_tests(tmp_path, inputs)
    inputs[path] = worker.sdk.sha(file.read_bytes())
    assert len(worker.authored_tests(tmp_path, inputs)) == len(worker.REQUIRED_TESTS) + 1


def private_lane():
    path = SUBJECT.with_name("ci_rust_wasm.py")
    spec = importlib.util.spec_from_file_location("worker_test_lane", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_second_official_runner_binary_keeps_original_pin_and_single_inode_guards(
    tmp_path,
):
    import os

    lane = private_lane()
    private = tmp_path / "private"
    work = private / "source"
    binary = work / ".ci-bindgen/bin/wasm-bindgen-test-runner"
    binary.parent.mkdir(parents=True, mode=0o700)
    binary.write_bytes(b"inert runner fixture, never executable by these tests")
    binary.chmod(0o700)
    package = private / "cargo/registry/src/inert-index/wasm-bindgen-cli-0.2.129"
    package.mkdir(parents=True)
    (package / "Cargo.toml").write_text(
        '[package]\nname="wasm-bindgen-cli"\nversion="0.2.129"\n'
    )
    (package / "Cargo.lock").write_text(
        'version=4\n[[package]]\nname="wasm-bindgen-cli"\nversion="0.2.129"\n'
    )
    archive = (
        private / "cargo/registry/cache/inert-index/wasm-bindgen-cli-0.2.129.crate"
    )
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"synthetic published crate fixture")
    synthetic_pin = (
        "0.2.129",
        "dd4afd5b4ed89dd2daca833fd225acf0676450b28f3cc0849f835e9ada9745e8",
    )
    with patch.object(lane, "BINDGEN_CRATE_PIN", synthetic_pin):
        before = lane.installed_bindgen_provenance(
            private, work, binary_name="wasm-bindgen-test-runner"
        )
        assert before["binarySha256"] == lane.sdk.sha(binary.read_bytes())
        alias = tmp_path / "unreviewed-runner-alias"
        os.link(binary, alias)
        with pytest.raises(worker.sdk.Refused):
            lane.installed_bindgen_provenance(
                private, work, binary_name="wasm-bindgen-test-runner"
            )
        with pytest.raises(worker.sdk.Refused):
            lane.detach_installed_bindgen(
                work, worker.time.monotonic() + 5, binary_name="../private-secret"
            )
        alias.unlink()
        release = work / ".ci-bindgen-target/release"
        (release / "deps").mkdir(parents=True, mode=0o700)
        for directory in [
            work,
            work / ".ci-bindgen",
            binary.parent,
            work / ".ci-bindgen-target",
            release,
            release / "deps",
        ]:
            directory.chmod(0o700)
        os.link(binary, release / "wasm-bindgen-test-runner")
        os.link(binary, release / "deps/wasm_bindgen_test_runner-0123456789abcdef")
        lane.detach_installed_bindgen(
            work, worker.time.monotonic() + 5, binary_name="wasm-bindgen-test-runner"
        )
        after = lane.installed_bindgen_provenance(
            private, work, binary_name="wasm-bindgen-test-runner"
        )
        assert (
            after["binarySha256"] == before["binarySha256"]
            and binary.stat().st_nlink == 1
        )


def test_legacy_primitive_exports_and_receipt_each_require_all_three_new_cases():
    required = (
        "real_webcrypto_equals_native_rust_and_independent_vectors_without_export",
        "every_original_scope_checkpoint_refuses_before_plaintext_publication",
        "dropped_consumer_wipes_late_real_decrypt_output",
    )
    original = (
        "cloned_nonextractable_key_preserves_nist_aes256_vector_and_never_exports",
        "extractable_key_uses_same_primitive_without_export_or_attribute_change",
        "wrong_key_tag_nonce_and_short_tag_fail_closed",
        "wrong_algorithm_length_usage_and_key_type_are_rejected",
        "capability_cancellation_denies_late_encrypt_and_decrypt_results",
        "same_material_new_capability_is_distinct_and_invalidated_old_result_cannot_publish",
        "dropped_consumer_still_wipes_real_webcrypto_plaintext_at_settlement",
        "shared_eleven_codec_cases_match_actual_webcrypto_for_both_extractability_values",
    )
    assert worker.REQUIRED_TESTS == original + required
    assert worker.wasm_tests(wasm())
    for name in required:
        with pytest.raises(worker.sdk.Refused):
            worker.wasm_tests(wasm(names=[n for n in worker.REQUIRED_TESTS if n != name]))
        receipt = proof()
        receipt["requiredTests"] = [n for n in receipt["requiredTests"] if not n.endswith("::" + name)]
        receipt["passed"] -= 1
        assert not worker.valid_proof(receipt)
