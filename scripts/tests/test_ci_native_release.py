# contract-test-file: tooling
"""Synthetic bytes/files only: no Cargo, ELF execution, Docker, CI or network."""

from copy import deepcopy
import datetime as dt
import io
import json
import os
from pathlib import Path
import stat
import struct
import tarfile
import pytest
from scripts import (
    ci_native_release as native,
    ci_artifacts as artifacts,
    ci_preparation_transport as transport,
)

SOURCE = "a" * 40
TREE = "b" * 40
HARNESS = "c" * 40


def binary():
    raw = bytearray(64)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<H", raw, 16, 3)
    struct.pack_into("<H", raw, 18, 62)
    return bytes(raw)


def wanted():
    return {
        "sourceCommit": SOURCE,
        "sourceTree": TREE,
        "harnessCommit": HARNESS,
        "contract": deepcopy(native.CONTRACT),
        "inputs": {"fixture.txt": "d" * 64},
        "recipe": {"scripts/ci_native_release.py": "e" * 64},
        "tools": {"cargo": {"sha256": "f" * 64}},
        "cargoConfiguration": {"cargo-home/config": None},
    }


def full_snapshot(target=0):
    observed = 2 * target + 2 * 1024**3
    return {
        "schemaVersion": 1,
        "cpuAffinity": 4,
        "cpuQuota": None,
        "memoryAvailableBytes": 16 * 1024**3,
        "cgroupMemoryMaxBytes": None,
        "cgroupMemoryCurrentBytes": None,
        "cgroup": {
            "cpu": {
                "version": "v2",
                "membership": "root",
                "scope": "visible-ancestors",
                "constraints": [None],
                "state": "unlimited",
            },
            "memory": {
                "version": "v2",
                "membership": "root",
                "scope": "visible-ancestors",
                "constraints": [{"maxBytes": None, "currentBytes": None}],
                "state": "unlimited",
            },
        },
        "targetAllocatedBytes": target,
        "diskFreeBytes": 64 * 1024**3,
        "diskTotalBytes": 128 * 1024**3,
        "observedReservationBytes": observed,
        "reservationFloorBytes": 6 * 1024**3,
        "reservationBytes": max(observed, 6 * 1024**3),
        "compilerJobCapacity": 4,
    }


def bundle(tmp_path, *, metadata=None, raw=None, rows=None):
    raw = binary() if raw is None else raw
    meta = {
        "status": "passed",
        "cleanupVerified": True,
        "identity": wanted(),
        "elfSha256": native.digest(raw),
        "elfBytes": len(raw),
        "runtime": {
            "osRelease": "1" * 64,
            "loader": "2" * 64,
            "dependencies": {"libc.so.6": "3" * 64},
        },
        "resources": {"compilerJobs": 4, "snapshotSha256": "4" * 64},
    }
    if metadata:
        metadata(meta)
    payload = native.canonical(meta)
    archive = tmp_path / native.ARCHIVE
    with tarfile.open(archive, "w:gz") as stream:
        items = (
            rows
            if rows is not None
            else [
                ("native-cli/identity.json", payload, 0o600, None),
                ("native-cli/openmates", raw, 0o700, None),
            ]
        )
        for name, data, mode, kind in items:
            entry = tarfile.TarInfo(name)
            entry.mode = mode
            entry.size = len(data)
            if kind:
                entry.type = kind
                entry.linkname = "outside"
            stream.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
    archive.chmod(0o600)
    item = {
        "path": native.ARCHIVE,
        "destination": native.DESTINATION,
        "size": archive.stat().st_size,
        "sha256": native.sha(archive),
        "identitySha256": native.digest(payload),
    }
    return archive, item, meta


def test_real_payload_parser_accepts_exact_closed_identity_and_x64_header(tmp_path):
    archive, item, meta = bundle(tmp_path)
    result, raw = native.validate_payload(archive, item, wanted())
    assert result == meta and raw == binary()


@pytest.mark.parametrize(
    "field",
    [
        "sourceCommit",
        "sourceTree",
        "harnessCommit",
        "contract",
        "inputs",
        "tools",
        "recipe",
        "cargoConfiguration",
    ],
)
def test_mismatched_source_profile_features_tools_config_and_full_closure_refuse(
    tmp_path, field
):
    def change(meta):
        meta["identity"][field] = "wrong"

    archive, item, _ = bundle(tmp_path, metadata=change)
    with pytest.raises(native.Refused, match="identity"):
        native.validate_payload(archive, item, wanted())


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "ci-unit"),
        ("target", "aarch64-unknown-linux-gnu"),
        ("rust", "1.98.0"),
        ("features", "all"),
        ("incremental", "1"),
        ("compilerPool", "arbitrary-8"),
        ("command", ["arbitrary", "executable"]),
    ],
)
def test_no_profile_target_feature_flag_or_command_equivalence(tmp_path, field, value):
    def change(meta):
        meta["identity"]["contract"][field] = value

    archive, item, _ = bundle(tmp_path, metadata=change)
    with pytest.raises(native.Refused):
        native.validate_payload(archive, item, wanted())


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("cleanupVerified", False),
        ("elfSha256", "0" * 64),
        ("elfBytes", 1),
    ],
)
def test_incomplete_producer_cleanup_or_digest_is_never_credited(
    tmp_path, field, value
):
    archive, item, _ = bundle(
        tmp_path, metadata=lambda meta: meta.update({field: value})
    )
    with pytest.raises(native.Refused):
        native.validate_payload(archive, item, wanted())


@pytest.mark.parametrize("fault", ["empty", "arm", "32bit", "relocatable"])
def test_actual_elf_header_parser_rejects_non_x64_release_executables(tmp_path, fault):
    raw = bytearray(binary())
    if fault == "empty":
        raw = bytearray()
    elif fault == "arm":
        struct.pack_into("<H", raw, 18, 183)
    elif fault == "32bit":
        raw[4] = 1
    else:
        struct.pack_into("<H", raw, 16, 1)
    archive, item, _ = bundle(tmp_path, raw=bytes(raw))
    with pytest.raises(native.Refused):
        native.validate_payload(archive, item, wanted())


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../escape"),
        ("destination", "/tmp/escape"),
        ("size", 1),
        ("sha256", "0" * 64),
        ("identitySha256", "0" * 64),
        ("unknown", True),
    ],
)
def test_archive_envelope_is_exact_and_integrity_checked(tmp_path, field, value):
    archive, item, _ = bundle(tmp_path)
    item[field] = value
    with pytest.raises(native.Refused):
        native.validate_payload(archive, item, wanted())


@pytest.mark.parametrize(
    "fault", ["symlink", "hardlink", "traversal", "extra", "mode", "duplicate"]
)
def test_streamed_member_validation_refuses_links_escapes_duplicates_modes_and_extras(
    tmp_path, fault
):
    name = "native-cli/openmates"
    kind = None
    mode = 0o700
    if fault == "symlink":
        kind = tarfile.SYMTYPE
    elif fault == "hardlink":
        kind = tarfile.LNKTYPE
    elif fault == "traversal":
        name = "../openmates"
    elif fault == "mode":
        mode = 0o777
    rows = [(name, binary(), mode, kind)]
    if fault == "extra":
        rows += [("arbitrary.exe", binary(), 0o700, None)]
    if fault == "duplicate":
        rows += [(name, binary(), mode, kind)]
    archive, item, _ = bundle(tmp_path, rows=rows)
    with pytest.raises(native.Refused):
        native.validate_payload(archive, item, wanted())


def test_malformed_and_duplicate_json_metadata_refuse_before_extraction(tmp_path):
    for body in [b"[]", b"{bad", b'{"status":"passed","status":"passed"}']:
        archive, item, _ = bundle(
            tmp_path,
            rows=[
                ("native-cli/openmates", binary(), 0o700, None),
                ("native-cli/identity.json", body, 0o600, None),
            ],
        )
        with pytest.raises((native.Refused, ValueError)):
            native.validate_payload(archive, item, wanted())


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "writable"])
def test_held_archive_refuses_unsafe_file_identity(tmp_path, fault):
    archive, item, _ = bundle(tmp_path)
    if fault == "symlink":
        archive.rename(tmp_path / "other")
        archive.symlink_to(tmp_path / "other")
    elif fault == "hardlink":
        os.link(archive, tmp_path / "other")
    else:
        archive.chmod(0o666)
    with pytest.raises(native.Refused):
        native.validate_payload(archive, item, wanted())


def test_owned_restore_checks_private_modes_and_never_overwrites_existing_destination(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "test-results").mkdir(mode=0o700)
    incoming = root / "test-results/ci-preparation-download"
    incoming.mkdir(mode=0o700)
    _, item, meta = bundle(incoming)
    monkeypatch.setattr(native, "identity", lambda *_: wanted())
    monkeypatch.setattr(native, "runtime_identity", lambda _: meta["runtime"])
    record = native.restore(root, incoming, item, SOURCE, TREE, HARNESS)
    assert (
        record["identity"] == wanted()
        and record["producerIdentitySha256"] == item["identitySha256"]
    )
    assert (root / native.DESTINATION / "openmates").read_bytes() == binary()
    assert stat.S_IMODE((root / native.DESTINATION).stat().st_mode) == 0o700
    assert stat.S_IMODE((root / native.RECEIPT).stat().st_mode) == 0o600
    with pytest.raises(native.Refused):
        native.restore(root, incoming, item, SOURCE, TREE, HARNESS)
    assert (root / native.DESTINATION / "openmates").read_bytes() == binary()


@pytest.mark.parametrize("fault", ["runtime", "destination-link", "parent-writable"])
def test_runtime_or_destination_refusal_leaves_no_usable_payload(
    tmp_path, monkeypatch, fault
):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    parent = root / "test-results"
    parent.mkdir(mode=0o700)
    incoming = root / "test-results/ci-preparation-download"
    incoming.mkdir(mode=0o700)
    _, item, meta = bundle(incoming)
    monkeypatch.setattr(native, "identity", lambda *_: wanted())
    monkeypatch.setattr(
        native,
        "runtime_identity",
        lambda _: {} if fault == "runtime" else meta["runtime"],
    )
    if fault == "destination-link":
        (root / native.DESTINATION).symlink_to(incoming, target_is_directory=True)
    if fault == "parent-writable":
        parent.chmod(0o777)
    with pytest.raises(native.Refused):
        native.restore(root, incoming, item, SOURCE, TREE, HARNESS)
    assert not (root / native.RECEIPT).exists()
    if fault == "runtime":
        assert not (root / native.DESTINATION).exists()
    assert (incoming / native.ARCHIVE).exists()


def test_build_refuses_non_ci_before_any_resource_or_tool_action(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        native, "identity", lambda *_: pytest.fail("must refuse before identity/tools")
    )
    with pytest.raises(native.Refused, match="isolated"):
        native.build(tmp_path, SOURCE, TREE, HARNESS)


def test_native_key_is_optional_closed_and_old_key_unchanged():
    old = {
        "format_version": artifacts.FORMAT_VERSION,
        "bundle_format": artifacts.BUNDLE_FORMAT,
        "producer_contract": artifacts.PRODUCER_CONTRACT,
        "source_commit": SOURCE,
        "capabilities": {"cli": True, "upload_runtime": False, "web": True},
        "build_environment": artifacts.DEFAULT_BUILD_ENVIRONMENT,
        "toolchain": artifacts.DEFAULT_TOOLCHAIN,
    }
    expected = native.digest(artifacts.canonical_json(old))
    assert artifacts.preparation_key(SOURCE) == expected
    key = artifacts.preparation_key(SOURCE, include_native_cli=True)
    assert key != expected
    assert artifacts.native_preparation(
        SOURCE, key
    ) and not artifacts.native_preparation(SOURCE, expected)
    for cli, upload in [(False, False), (True, True)]:
        with pytest.raises(ValueError):
            artifacts.preparation_key(
                SOURCE, include_cli=cli, include_upload=upload, include_native_cli=True
            )
    assert native.SCOPES == frozenset(
        ["cli-native-bounded-saved-read.spec.ts", "cli-rust-core-essential.spec.ts"]
    )


def public_fixture(root):
    for relative in [
        "frontend/apps/web_app/build",
        "frontend/apps/web_app/.svelte-kit/output",
        "frontend/packages/ui/src/i18n/locales",
        "frontend/packages/openmates-cli/dist",
    ]:
        p = root / relative
        p.mkdir(parents=True)
        (p / "fixture.txt").write_text("inert")


def test_old_default_bundles_remain_native_free_and_optional_failure_cold_falls_back(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    public_fixture(root)
    output = tmp_path / "bundle"
    old = artifacts.create_bundle(
        root,
        output,
        SOURCE,
        candidate_tree=TREE,
        harness_commit=HARNESS,
        include_cli=True,
        include_upload=False,
    )
    assert (
        "native_cli" not in old["capabilities"] and "native_cli" not in old["artifacts"]
    )
    monkeypatch.setattr(
        native, "package", lambda *_: (_ for _ in ()).throw(native.Refused("missing"))
    )
    with pytest.raises(ValueError, match="Required native preparation unavailable"):
        artifacts.create_bundle(
            root,
            output,
            SOURCE,
            candidate_tree=TREE,
            harness_commit=HARNESS,
            include_cli=True,
            include_upload=False,
            include_native_cli=True,
        )
    new = {
        **old,
        "preparation_key": artifacts.preparation_key(
            SOURCE, include_cli=True, include_upload=False, include_native_cli=True
        ),
        "capabilities": {**old["capabilities"], "native_cli": False},
    }
    (output / artifacts.MANIFEST_NAME).write_text(json.dumps(new))
    assert new["capabilities"]["native_cli"] is False
    result = artifacts.restore_bundle(
        root,
        output,
        SOURCE,
        candidate_tree=TREE,
        harness_commit=HARNESS,
        include_cli=True,
        include_upload=False,
        include_native_cli=True,
    )
    assert (
        result["reused"] is False
        and result["cold_fallback"] is True
        and result["reason"] == "native_cli_capability_missing"
    )


def signer(objects, seconds):
    assert seconds == 48 * 60 * 60
    return {
        p: {
            kind
            + "_url": f"https://nbg1.your-objectstorage.com/{transport.BUCKET_NAME}/{key}?X-Amz-Operation={kind}&X-Amz-Signature=inert"
            for kind in ["put", "get"]
        }
        for p, key in objects.items()
    }


@pytest.mark.parametrize("native_requested", [False, True])
def test_real_ticket_parser_preserves_old_shape_and_binds_native_object_to_key_and_role(
    tmp_path, native_requested
):
    key = artifacts.preparation_key(SOURCE, include_native_cli=native_requested)
    ticket = transport.get_or_create_ticket(
        tmp_path,
        "d" * 64,
        SOURCE,
        key,
        now=dt.datetime.now(dt.timezone.utc),
        presign=signer,
    )
    assert (transport.NATIVE_PATH in ticket["objects"]) is native_requested
    producer = transport._dispatch_view(ticket, producer=True)
    consumer = transport._dispatch_view(ticket, producer=False)
    inputs = {
        "mode": "e2e",
        "prepare_native_cli": "true" if native_requested else "false",
    }
    assert (
        transport.validate_event_role(consumer, inputs, command="download")
        == "consumer"
    )
    for role, view, command in [
        ("prepare", producer, "upload"),
        ("e2e", consumer, "download"),
    ]:
        assert transport.validate_event_role(
            view,
            {"mode": role, "prepare_native_cli": inputs["prepare_native_cli"]},
            command=command,
        )
        altered = deepcopy(view)
        if native_requested:
            altered["objects"].pop(transport.NATIVE_PATH)
        else:
            altered["objects"][transport.NATIVE_PATH] = next(
                iter(altered["objects"].values())
            )
        with pytest.raises(transport.PreparationTransportError):
            transport.validate_event_role(altered, {"mode": role}, command=command)
    if native_requested:
        altered = deepcopy(consumer)
        altered["objects"]["arbitrary.tar.gz"] = altered["objects"][
            transport.NATIVE_PATH
        ]
        with pytest.raises(transport.PreparationTransportError):
            transport.validate_event_role(altered, inputs, command="download")


@pytest.mark.parametrize(
    "affinity,quota,state,expected",
    [
        (4, None, "unlimited", 4),
        (32, None, "unlimited", 8),
        (4, 2.5, "limited", 2),
        (1, 1, "limited", 1),
    ],
)
def test_producer_uses_normal_effective_cpu_capacity_in_one_compiler_pool(
    affinity, quota, state, expected
):
    assert (
        native.compiler_jobs(
            {
                "cpuAffinity": affinity,
                "cpuQuota": quota,
                "cgroup": {"cpu": {"state": state}},
            }
        )
        == expected
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {},
        {
            "cpuAffinity": True,
            "cpuQuota": None,
            "cgroup": {"cpu": {"state": "unlimited"}},
        },
        {
            "cpuAffinity": 4,
            "cpuQuota": None,
            "cgroup": {"cpu": {"state": "controller-unavailable"}},
        },
        {"cpuAffinity": 4, "cpuQuota": None, "cgroup": {"cpu": {"state": "limited"}}},
        {"cpuAffinity": 4, "cpuQuota": 0.5, "cgroup": {"cpu": {"state": "limited"}}},
        {
            "cpuAffinity": 4,
            "cpuQuota": float("nan"),
            "cgroup": {"cpu": {"state": "limited"}},
        },
    ],
)
def test_missing_unknown_or_malformed_cpu_provenance_refuses_optional_compiler(
    snapshot,
):
    with pytest.raises(native.Refused):
        native.compiler_jobs(snapshot)


def test_package_preserves_shared_cargo_hardlinks_and_makes_private_transport_copy(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "test-results").mkdir(mode=0o700)
    target = root / native.NATIVE / "target/release"
    target.mkdir(parents=True)
    elf = target / "openmates"
    elf.write_bytes(binary())
    elf.chmod(0o755)
    os.link(elf, target / "shared-cargo-inode")
    before = elf.stat()
    meta = {
        "status": "passed",
        "cleanupVerified": True,
        "identity": wanted(),
        "elfSha256": native.sha(elf),
        "elfBytes": elf.stat().st_size,
        "runtime": {
            "osRelease": "1" * 64,
            "loader": "2" * 64,
            "dependencies": {"libc.so.6": "3" * 64},
        },
        "resources": {"compilerJobs": 4, "snapshotSha256": "4" * 64},
    }
    receipt = root / native.BUILD_RECEIPT
    receipt.write_text(json.dumps(meta))
    receipt.chmod(0o600)
    monkeypatch.setattr(native, "identity", lambda *_: wanted())
    monkeypatch.setattr(native, "runtime_identity", lambda _: meta["runtime"])
    output = root / "test-results/ci-preparation"
    output.mkdir(mode=0o700)
    item = native.package(root, output, SOURCE, TREE, HARNESS)
    parsed, raw = native.validate_payload(output / native.ARCHIVE, item, wanted())
    assert raw == binary() and parsed == meta
    after = elf.stat()
    assert (before.st_ino, before.st_mode, before.st_nlink) == (
        after.st_ino,
        after.st_mode,
        after.st_nlink,
    )
    assert (
        after.st_nlink == 2
        and stat.S_IMODE((output / native.ARCHIVE).stat().st_mode) == 0o600
    )
    assert not list(output.glob(".native-cli-*.tmp"))


@pytest.mark.parametrize("fault", ["", "admission", "unknown_cleanup", "cancel"])
def test_actual_optional_producer_scheduler_admission_jobs_deadlines_and_joined_refusals(
    tmp_path, monkeypatch, fault
):
    from contextlib import contextmanager
    from scripts import resource_budget, ci_client_owned_lifecycle as lifecycle

    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "test-results").mkdir(mode=0o700)
    (root / native.NATIVE).mkdir(parents=True)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(native, "identity", lambda *_: wanted())
    monkeypatch.setattr(
        native, "resource_program", lambda _: "inert resource literal, never executed"
    )
    monkeypatch.setattr(
        native,
        "verify_dispatch",
        lambda *_: {"cargo": "/verified/cargo", "python3": "/usr/bin/python3"},
    )
    runtime = {
        "osRelease": "1" * 64,
        "loader": "2" * 64,
        "dependencies": {"libc.so.6": "3" * 64},
    }
    monkeypatch.setattr(native, "runtime_identity", lambda _: runtime)
    calls = []
    events = []
    original = native.fcntl.flock

    def flock(fd, mode):
        events.append("flock")
        return original(fd, mode)

    monkeypatch.setattr(native.fcntl, "flock", flock)

    @contextmanager
    def reserve(repository, amount, **kwargs):
        assert events == ["flock"]
        assert repository == root and amount == 6 * 1024**3
        assert kwargs["operation"] == "native-prepared-release"
        events.append("admission")
        if fault == "admission":
            raise RuntimeError("normal guard refusal")
        try:
            yield {"inert": True}
        finally:
            events.append("released")

    monkeypatch.setattr(resource_budget, "reserve", reserve)

    def run(argv, **kwargs):
        name = kwargs["out"].name
        calls.append(
            {
                "name": name,
                "argv": argv,
                "env": kwargs["env"],
                "timeout": kwargs["timeout"],
            }
        )
        kwargs["attempt"].update(
            cleanupVerified=True,
            cleanup={
                "groupEmpty": fault != "unknown_cleanup",
                "inspectionUnknown": False,
            },
        )
        if name == "resources":
            (kwargs["out"] / "process.log").write_text(
                json.dumps(full_snapshot()) + "\n"
            )
        if name == "release":
            binary = root / native.NATIVE / "target/release/openmates"
            binary.parent.mkdir()
            binary.write_bytes(globals()["binary"]())
            binary.chmod(0o755)
        return 130 if fault == "cancel" and name == "release" else 0

    monkeypatch.setattr(lifecycle, "run_owned", run)
    if fault:
        with pytest.raises((native.Refused, RuntimeError)):
            native.build(root, SOURCE, TREE, HARNESS)
    else:
        native.build(root, SOURCE, TREE, HARNESS)
    record = json.loads((root / native.BUILD_RECEIPT).read_text())
    assert record["status"] == ("failed" if fault else "passed")
    if fault == "admission":
        assert calls == []
    elif fault == "unknown_cleanup":
        assert [v["name"] for v in calls] == ["resources"]
    else:
        assert [v["timeout"] for v in calls] == [15, 120, 30, 540]
        assert (
            calls[-1]["env"]["CARGO_BUILD_JOBS"] == "4"
            and calls[-1]["env"]["CARGO_INCREMENTAL"] == "0"
        )
        assert calls[-1]["argv"][0:5] == [
            "/verified/cargo",
            "+1.98.1",
            "build",
            "--release",
            "--locked",
        ]
        assert (
            "--offline" in calls[-1]["argv"]
            and "RUSTFLAGS" not in calls[-1]["env"]
            and "GOOGLE_API_KEY" not in calls[-1]["env"]
        )
    if fault != "admission":
        assert events[-1] == "released"
    if not fault:
        assert (
            record["resources"]["compilerJobs"] == 4
            and len(record["resources"]["snapshotSha256"]) == 64
        )


@pytest.mark.parametrize(
    "fault", ["", "foreign-host", "unknown-library", "wrong-loader"]
)
def test_actual_runtime_inspector_uses_only_fixed_paths_and_refuses_unknown_dependencies(
    tmp_path, monkeypatch, fault
):
    elf = tmp_path / "openmates"
    elf.write_bytes(binary())
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        native.platform,
        "machine",
        lambda: "aarch64" if fault == "foreign-host" else "x86_64",
    )
    calls = []

    def inspect(argv, **_kwargs):
        calls.append(argv)
        assert argv[0] == "/usr/bin/readelf" and argv[-1] in (
            str(elf),
            native.LIBRARIES["libc.so.6"],
        )
        if argv[1] == "-d":
            return (
                " (NEEDED) Shared library: ["
                + ("evil.so" if fault == "unknown-library" else "libc.so.6")
                + "]\n"
            )
        return (
            "[Requesting program interpreter: "
            + ("/arbitrary/loader" if fault == "wrong-loader" else native.LOADER)
            + "]\n"
        )

    monkeypatch.setattr(native.subprocess, "check_output", inspect)
    monkeypatch.setattr(native, "sha", lambda p: native.digest(str(p).encode()))
    monkeypatch.setattr(
        native,
        "loader_cache",
        lambda: (
            {
                "sha256": native.digest(str(native.LOADER_CACHE).encode()),
                "inspectorSha256": "8" * 64,
            },
            {"libc.so.6": [("libc6,x86-64", native.LIBRARIES["libc.so.6"])]},
        ),
    )
    monkeypatch.setattr(
        native, "system_digest", lambda p, *_: native.digest(str(p).encode())
    )
    monkeypatch.setattr(native, "inspect_elf", lambda _: None)
    monkeypatch.setattr(native, "loader_environment", lambda: None)
    if fault:
        with pytest.raises(native.Refused):
            native.runtime_identity(elf)
    else:
        result = native.runtime_identity(elf)
        assert result["dependencies"] == {
            "libc.so.6": {
                "path": native.LIBRARIES["libc.so.6"],
                "sha256": native.digest(native.LIBRARIES["libc.so.6"].encode()),
            }
        }
        assert (
            result["loader"] == native.digest(native.LOADER.encode())
            and len(calls) == 3
        )
    if fault == "foreign-host":
        assert calls == []


def test_resource_resolver_reuses_exact_maintained_literal_without_runtime_override(
    tmp_path,
):
    # Separate tiny synthetic source fixture exercises the actual bounded literal
    # extractor; cgroup resolver behavior remains covered by its maintained tests.
    root = tmp_path / "root"
    p = root / "frontend/apps/web_app/tests/cli-rust-core-essential.spec.ts"
    p.parent.mkdir(parents=True)
    p.write_text('const NATIVE_RESOURCE_SNAPSHOT=String.raw`\nprint("inert")\n`;\n')
    assert native.resource_program(root) == '\nprint("inert")\n'
    p.write_text(p.read_text() + p.read_text())
    with pytest.raises(native.Refused, match="resource_source"):
        native.resource_program(root)


@pytest.mark.parametrize("code,expected", [(0, True), (128, False)])
def test_old_subject_without_new_consumer_cannot_request_native_capability(
    tmp_path, monkeypatch, code, expected
):
    def call(argv, **kwargs):
        assert argv == [
            "/usr/bin/git",
            "-C",
            str(tmp_path),
            "cat-file",
            "-e",
            SOURCE + ":frontend/apps/web_app/tests/helpers/native-prepared-release.cjs",
        ]
        assert kwargs["timeout"] == 5 and kwargs["capture_output"] is True
        return type("Result", (), {"returncode": code})()

    monkeypatch.setattr(native.subprocess, "run", call)
    assert native.source_eligible(tmp_path, SOURCE) is expected


def test_actual_maintained_resource_literal_remains_python_parseable():
    root = Path(__file__).resolve().parents[2]
    program = native.resource_program(root)
    assert "controller-unavailable" in program and "/proc/self/cgroup" in program
    compile(program, "<maintained-resource-snapshot>", "exec")  # parse only; no probe


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    ],
)
def test_extensions_refuse_header_before_declared_body_is_read(
    tmp_path, monkeypatch, kind
):
    import gzip

    header = tarfile.TarInfo("native-cli/identity.json")
    header.type = kind
    header.size = 2**32
    archive = tmp_path / native.ARCHIVE
    archive.write_bytes(gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT)))
    archive.chmod(0o600)
    item = {
        "path": native.ARCHIVE,
        "destination": native.DESTINATION,
        "size": archive.stat().st_size,
        "sha256": native.sha(archive),
        "identitySha256": "0" * 64,
    }
    reads = []
    original = native._BoundedGzip.read

    def read(self, count):
        reads.append(count)
        return original(self, count)

    monkeypatch.setattr(native._BoundedGzip, "read", read)
    with pytest.raises(native.Refused, match="header_form"):
        native.validate_payload(archive, item, wanted())
    assert reads == [512]


def test_aggregate_decompression_and_allocation_request_are_bounded(
    tmp_path, monkeypatch
):
    import gzip

    archive, item, _ = bundle(tmp_path)
    # Highly compressible concatenated gzip payload cannot evade the aggregate
    # decompressed-byte bound after the two accepted members/end markers.
    archive.write_bytes(archive.read_bytes() + gzip.compress(b"\0" * 65536))
    archive.chmod(0o600)
    item.update(size=archive.stat().st_size, sha256=native.sha(archive))
    monkeypatch.setattr(native, "STREAM_LIMIT", 16384)
    with pytest.raises(native.Refused, match="decompression_bound"):
        native.validate_payload(archive, item, wanted())
    reader = native._BoundedGzip(io.BytesIO(gzip.compress(b"abc")))
    with pytest.raises(native.Refused, match="read_bound"):
        reader.read(native.READ_LIMIT + 1)
    assert reader.total == 0


@pytest.mark.parametrize(
    "tag",
    [
        "RPATH",
        "RUNPATH",
        "FILTER",
        "AUXILIARY",
        "AUDIT",
        "DEPAUDIT",
        "CONFIG",
        "FLAGS_1",
    ],
)
def test_actual_dynamic_inspector_refuses_loader_redirection_before_dependencies(
    tmp_path, monkeypatch, tag
):
    path = tmp_path / "openmates"
    path.write_bytes(binary())
    calls = []
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    monkeypatch.setattr(native.platform, "machine", lambda: "x86_64")

    def inspect(argv, **_kwargs):
        calls.append(argv)
        return (
            "(NEEDED) Shared library: [libc.so.6]\n ("
            + tag
            + ") "
            + ("Flags: NODEFLIB" if tag == "FLAGS_1" else "Library: [arbitrary]")
            + "\n"
        )

    monkeypatch.setattr(native.subprocess, "check_output", inspect)
    with pytest.raises(native.Refused, match="loader_redirection"):
        native.runtime_identity(path)
    assert len(calls) == 1 and calls[0][1] == "-d"


def dispatch_fixture(tmp_path, monkeypatch):
    home = tmp_path / "home"
    proxies = home / ".cargo/bin"
    proxies.mkdir(parents=True)
    rustup = proxies / "rustup"
    rustup.write_bytes(b"pinned-rustup")
    rustup.chmod(0o700)
    for name in ("cargo", "rustc", "rustdoc"):
        (proxies / name).hardlink_to(rustup)
    compiler = home / ".rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin"
    compiler.mkdir(parents=True)
    tools = {"rustup": {"sha256": native.sha(rustup)}}
    for name in ("cargo", "rustc"):
        p = compiler / name
        p.write_bytes(("pinned-" + name).encode())
        tools[name] = {"sha256": native.sha(p)}
    for name in ("python3", "cc", "ld", "ar", "readelf", "git"):
        tools[name] = {"sha256": native.sha(Path("/usr/bin") / name)}
    monkeypatch.setenv("HOME", str(home))
    return {"PATH": str(proxies) + ":/usr/bin"}, tools, proxies


def test_dispatch_accepts_actual_same_inode_proxies_and_fixed_system_tools(
    tmp_path, monkeypatch
):
    environment, tools, proxies = dispatch_fixture(tmp_path, monkeypatch)
    paths = native.verify_dispatch(environment, tools)
    assert (
        paths["cargo"] == str(proxies / "cargo")
        and paths["python3"] == "/usr/bin/python3"
    )


@pytest.mark.parametrize(
    "name",
    [
        "cargo",
        "rustc",
        "rustdoc",
        "rustup",
        "python3",
        "cc",
        "ld",
        "ar",
        "readelf",
        "git",
    ],
)
def test_dispatch_refuses_shadow_executables_even_when_bytes_match(
    tmp_path, monkeypatch, name
):
    environment, tools, proxies = dispatch_fixture(tmp_path, monkeypatch)
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    selected = shadow / name
    original = (
        proxies / name
        if name in ("cargo", "rustc", "rustdoc", "rustup")
        else Path("/usr/bin") / name
    )
    selected.write_bytes(original.read_bytes())
    selected.chmod(0o700)
    environment["PATH"] = str(shadow) + ":" + environment["PATH"]
    with pytest.raises(native.Refused, match="tool_path"):
        native.verify_dispatch(environment, tools)


def test_dispatch_refuses_changed_pinned_compiler_after_phase(tmp_path, monkeypatch):
    environment, tools, _ = dispatch_fixture(tmp_path, monkeypatch)
    native.verify_dispatch(environment, tools)
    path = Path.home() / ".rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin/cargo"
    path.write_bytes(b"changed")
    with pytest.raises(native.Refused, match="tool_dispatch_digest"):
        native.verify_dispatch(environment, tools)


@pytest.mark.parametrize(
    "target,expected", [(0, 6), (4 * 1024**3, 10), (64 * 1024**3, 130)]
)
def test_v3_existing_resource_snapshot_exact_formula_and_growth(target, expected):
    value = full_snapshot(target)
    assert native.resource_snapshot(value) is value
    assert value["reservationBytes"] == expected * 1024**3


@pytest.mark.parametrize(
    "field,value",
    [
        ("observedReservationBytes", 0),
        ("reservationFloorBytes", 1),
        ("reservationBytes", 1),
        ("compilerJobCapacity", 8),
        ("cpuAffinity", True),
        ("diskTotalBytes", 0),
        ("schemaVersion", 2),
        ("cgroupMemoryCurrentBytes", 7),
        ("cpuQuota", 3),
        ("extra", True),
        ("memoryAvailableBytes", 2**53),
    ],
)
def test_v3_full_snapshot_inconsistencies_fail_closed(field, value):
    snapshot = full_snapshot()
    snapshot[field] = value
    with pytest.raises(native.Refused, match="resource_snapshot"):
        native.resource_snapshot(snapshot)


def test_v3_resource_snapshot_over_130_gib_is_not_admitted():
    with pytest.raises(native.Refused, match="resource_snapshot"):
        native.resource_snapshot(full_snapshot(65 * 1024**3))


@pytest.mark.parametrize(
    "variable",
    [
        "LD_AUDIT",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_HWCAP_MASK",
        "GLIBC_TUNABLES",
        "GLIBC_HWCAPS",
    ],
)
def test_v3_loader_environment_does_not_admit_audit_or_search_overrides(
    monkeypatch, variable
):
    monkeypatch.setenv(variable, "not-executed")
    with pytest.raises(native.Refused, match="loader_environment"):
        native.loader_environment()


def test_v3_loader_preload_file_even_empty_or_dangling_is_refused(monkeypatch):
    monkeypatch.setattr(native.os.path, "lexists", lambda p: p == "/etc/ld.so.preload")
    with pytest.raises(native.Refused, match="loader_preload"):
        native.loader_environment()


@pytest.mark.parametrize(
    "text",
    [
        "libc.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libc.so.6\nlibc.so.6 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libc.so.6",
        'libc.so.6 (libc6,x86-64, hwcap: "x86-64-v3") => /lib/x86_64-linux-gnu/glibc-hwcaps/x86-64-v3/libc.so.6',
        "libc.so.6 (libc6) => /lib/x86_64-linux-gnu/libc.so.6",
        "libc.so.6 (libc6,x86-64) => /unbound/libc.so.6",
    ],
)
def test_v3_cache_selection_refuses_ambiguous_hwcap_abi_and_unbound_paths(text):
    rows = native.cache_entries(text)
    with pytest.raises(native.Refused):
        native.cache_dependency(rows, "libc.so.6")


def test_v3_cache_parser_requires_bounded_complete_entries():
    with pytest.raises(native.Refused):
        native.cache_entries("libc.so.6 => malformed")
    with pytest.raises(native.Refused):
        native.cache_entries("x" * (1024**2 + 1))
    rows = native.cache_entries(
        "libc.so.6 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libc.so.6"
    )
    assert native.cache_dependency(rows, "libc.so.6") == Path(
        "/usr/lib/x86_64-linux-gnu/libc.so.6"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "",
        "transitive-redirect",
        "missing-transitive",
        "changed-cache",
        "changed-library",
        "loader-self-mismatch",
    ],
)
def test_v3_actual_recursive_runtime_closure_without_candidate_execution(
    tmp_path, monkeypatch, fault
):
    path = tmp_path / "openmates"
    path.write_bytes(binary())
    calls = []
    counts = {}
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    monkeypatch.setattr(native.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        native, "inspect_elf", lambda p: calls.append(("header", str(p)))
    )
    monkeypatch.setattr(native, "loader_environment", lambda: None)
    rows = {
        "libc.so.6": [("libc6,x86-64", "/usr/lib/x86_64-linux-gnu/libc.so.6")],
        "ld-linux-x86-64.so.2": [
            ("libc6,x86-64", "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2")
        ],
    }
    if fault == "missing-transitive":
        del rows["ld-linux-x86-64.so.2"]
    cache_hash = native.digest(str(native.LOADER_CACHE).encode())
    monkeypatch.setattr(
        native,
        "loader_cache",
        lambda: ({"sha256": cache_hash, "inspectorSha256": "9" * 64}, rows),
    )

    def system(p, *_):
        p = str(p)
        counts[p] = counts.get(p, 0) + 1
        if fault == "changed-cache" and p == str(native.LOADER_CACHE):
            return "0" * 64
        if fault == "changed-library" and p.endswith("/libc.so.6") and counts[p] > 1:
            return "0" * 64
        if p.endswith("/ld-linux-x86-64.so.2") and fault != "loader-self-mismatch":
            return native.digest(native.LOADER.encode())
        return native.digest(p.encode())

    monkeypatch.setattr(native, "system_digest", system)

    def inspect(argv, **_):
        assert argv[0] == "/usr/bin/readelf"
        calls.append(("readelf", argv[-1]))
        if argv[1] == "-l":
            return "[Requesting program interpreter: " + native.LOADER + "]"
        if argv[-1] == str(path):
            return "(NEEDED) Shared library: [libc.so.6]"
        if argv[-1].endswith("/libc.so.6"):
            return "(NEEDED) Shared library: [ld-linux-x86-64.so.2]" + (
                "\n(RUNPATH) [/untrusted]" if fault == "transitive-redirect" else ""
            )
        return ""

    monkeypatch.setattr(native.subprocess, "check_output", inspect)
    if fault:
        with pytest.raises(native.Refused):
            native.runtime_identity(path)
    else:
        result = native.runtime_identity(path)
        assert set(result["dependencies"]) == {"libc.so.6", "ld-linux-x86-64.so.2"}
        assert (
            result["dependencies"]["libc.so.6"]["path"]
            == "/usr/lib/x86_64-linux-gnu/libc.so.6"
        )
        assert len([c for c in calls if c[0] == "readelf"]) == 4


@pytest.mark.parametrize(
    "target,refuse_extra",
    [(4 * 1024**3, False), (4 * 1024**3, True), (65 * 1024**3, False)],
)
def test_v3_growth_reservation_precedes_fetch_and_failed_admission_never_builds(
    tmp_path, monkeypatch, target, refuse_extra
):
    from contextlib import contextmanager
    from scripts import resource_budget, ci_client_owned_lifecycle as lifecycle

    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "test-results").mkdir(mode=0o700)
    (root / native.NATIVE).mkdir(parents=True)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(native, "identity", lambda *_: wanted())
    monkeypatch.setattr(native, "resource_program", lambda _: "inert")
    monkeypatch.setattr(
        native,
        "verify_dispatch",
        lambda *_: {"cargo": "/verified/cargo", "python3": "/usr/bin/python3"},
    )
    monkeypatch.setattr(native, "runtime_identity", lambda _: {"inert": True})
    active = []
    events = []

    @contextmanager
    def reserve(repository, amount, **kwargs):
        assert repository == root and kwargs["operation"] == (
            "native-prepared-release-growth" if active else "native-prepared-release"
        )
        events.append(("reserve", amount))
        if refuse_extra and active:
            raise RuntimeError("inert extra admission refusal")
        active.append(amount)
        try:
            yield {}
        finally:
            active.remove(amount)
            events.append(("release", amount))

    monkeypatch.setattr(resource_budget, "reserve", reserve)

    def run(argv, **kwargs):
        name = kwargs["out"].name
        events.append(("phase", name))
        kwargs["attempt"].update(
            cleanupVerified=True,
            cleanup={"groupEmpty": True, "inspectionUnknown": False},
        )
        if name == "resources":
            (kwargs["out"] / "process.log").write_text(
                json.dumps(full_snapshot(target))
            )
        else:
            assert sum(active) == full_snapshot(target)["reservationBytes"]
        if name == "release":
            binary_path = root / native.NATIVE / "target/release/openmates"
            binary_path.parent.mkdir()
            binary_path.write_bytes(binary())
            binary_path.chmod(0o755)
        return 0

    monkeypatch.setattr(lifecycle, "run_owned", run)
    if refuse_extra or target > 64 * 1024**3:
        with pytest.raises((native.Refused, RuntimeError)):
            native.build(root, SOURCE, TREE, HARNESS)
        assert [v for k, v in events if k == "phase"] == ["resources"]
    else:
        native.build(root, SOURCE, TREE, HARNESS)
        assert events.index(("reserve", 4 * 1024**3)) < events.index(("phase", "fetch"))
        assert [v for k, v in events if k == "phase"] == [
            "resources",
            "fetch",
            "package-inputs",
            "release",
        ]
    assert active == []


@pytest.mark.parametrize(
    "fault",
    ["", "cache-drift", "inspector-drift", "oversized", "malformed", "nonascii"],
)
def test_v3_actual_cache_inspector_is_fixed_bounded_rechecked_and_never_runs_candidate(
    monkeypatch, fault
):
    monkeypatch.setattr(native, "loader_environment", lambda: None)
    counts = {}
    calls = []

    def system(path, *_):
        key = str(path)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > 1 and (
            (fault == "cache-drift" and path == native.LOADER_CACHE)
            or (fault == "inspector-drift" and path == native.CACHE_INSPECTOR)
        ):
            return "0" * 64
        return native.digest(key.encode())

    monkeypatch.setattr(native, "system_digest", system)

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv == ["/usr/sbin/ldconfig", "-p", "-C", "/etc/ld.so.cache"]
        assert (
            kwargs["timeout"] == 10
            and kwargs["check"] is True
            and kwargs["stderr"] == native.subprocess.DEVNULL
        )
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        raw = b"1 libs found in cache `/etc/ld.so.cache`\n libc.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libc.so.6\n"
        if fault == "oversized":
            raw = b"x" * (1024**2 + 1)
        if fault == "malformed":
            raw = b"libc.so.6 => malformed"
        if fault == "nonascii":
            raw = b"\xff"
        kwargs["stdout"].write(raw)

    monkeypatch.setattr(native.subprocess, "run", run)
    if fault:
        with pytest.raises((native.Refused, UnicodeDecodeError)):
            native.loader_cache()
    else:
        receipt, rows = native.loader_cache()
        assert receipt["sha256"] == native.digest(str(native.LOADER_CACHE).encode())
        assert native.cache_dependency(rows, "libc.so.6") == Path(
            "/lib/x86_64-linux-gnu/libc.so.6"
        )
    assert len(calls) == 1


def actual_private_coordinator(tmp_path, monkeypatch, thread):
    # Real state/request/claim/release + real resource_budget reservation adapter.
    # Only scheduler grant readiness, capacity and process identity are synthetic;
    # no live service, registration marker, git, account or product is accessed.
    from types import SimpleNamespace
    from scripts import (
        disk_coordinator_state as ledger,
        disk_coordinator,
        resource_budget,
    )

    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    state = ledger.CoordinatorState(
        tmp_path / "ledger",
        usage=lambda _: SimpleNamespace(
            total=256 * 1024**3, used=0, free=256 * 1024**3
        ),
        inodes=lambda _: 1000000,
        clock=lambda: 1000,
    )
    monkeypatch.setattr(ledger, "canonical_repository", lambda p: Path(p).resolve())
    monkeypatch.setattr(
        disk_coordinator, "canonical_repository", lambda p: Path(p).resolve()
    )
    monkeypatch.setattr(ledger, "filesystem", lambda _: "inert-filesystem")
    monkeypatch.setattr(resource_budget, "_start_time", lambda _: "inert-start")
    monkeypatch.setattr(ledger, "allocation_exited", lambda _: False)
    monkeypatch.setattr(state, "available", lambda: True)
    monkeypatch.setattr(disk_coordinator, "configured", lambda _: state)
    if thread:
        monkeypatch.setenv("CODEX_THREAD_ID", thread)
    else:
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    with state.db(write=True) as db:
        db.execute("INSERT INTO repositories VALUES (?,1,?)", (str(root), "[]"))
    real_request = state.request
    real_release = state.release
    events = []

    def request(*args, **kwargs):
        row = real_request(*args, **kwargs)
        events.append(("request", kwargs["operation"], row["amount"], row["id"]))
        if row["state"] == "waiting":
            # Stand in ONLY for the elected service's grant readiness. Actual
            # claim below still performs its normal capacity/committed checks.
            with state.db(write=True) as db:
                db.execute(
                    "UPDATE requests SET state='granted',grant_id=?,expires_at=? WHERE id=?",
                    ("inert-grant-" + row["id"], 2000, row["id"]),
                )
        return state.get(row["id"])

    def release(identity):
        real_release(identity)
        events.append(("release", state.get(identity)["operation"]))

    monkeypatch.setattr(state, "request", request)
    monkeypatch.setattr(state, "release", release)
    return root, state, events


@pytest.mark.parametrize("extra", [4 * 1024**3, 6 * 1024**3])
@pytest.mark.parametrize("thread", ["", "11111111-1111-4111-8111-111111111111"])
def test_v4_actual_coordinator_reproduces_v3_equal_and_unequal_operation_collision(
    tmp_path, monkeypatch, extra, thread
):
    from scripts import resource_budget

    root, state, events = actual_private_coordinator(tmp_path, monkeypatch, thread)
    error = RuntimeError if extra == 6 * 1024**3 else ValueError
    text = (
        "live allocation owner"
        if extra == 6 * 1024**3
        else "different capacity requirements"
    )
    with resource_budget.reserve(
        root, 6 * 1024**3, operation="native-prepared-release"
    ):
        with pytest.raises(error, match=text):
            with resource_budget.reserve(
                root, extra, operation="native-prepared-release"
            ):
                pytest.fail("V3 collision must not yield")
        rows = state.requests(root)
        assert (
            len(rows) == 1
            and rows[0]["state"] == "claimed"
            and rows[0]["outstanding"] == 6 * 1024**3
        )
    rows = state.requests(root)
    assert (
        len(rows) == 1
        and rows[0]["state"] == "complete"
        and rows[0]["outstanding"] == 0
    )
    assert events[-1] == ("release", "native-prepared-release")


@pytest.mark.parametrize(
    "target,extra", [(4 * 1024**3, 4 * 1024**3), (5 * 1024**3, 6 * 1024**3)]
)
@pytest.mark.parametrize("fail_fetch", [False, True])
@pytest.mark.parametrize("thread", ["", "11111111-1111-4111-8111-111111111111"])
def test_v4_actual_coordinator_distinct_growth_claim_and_exitstack_unwind(
    tmp_path, monkeypatch, target, extra, fail_fetch, thread
):
    from scripts import ci_client_owned_lifecycle as lifecycle

    root, state, events = actual_private_coordinator(tmp_path, monkeypatch, thread)
    (root / "test-results").mkdir(mode=0o700)
    (root / native.NATIVE).mkdir(parents=True)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(native, "identity", lambda *_: wanted())
    monkeypatch.setattr(native, "resource_program", lambda _: "inert")
    monkeypatch.setattr(
        native,
        "verify_dispatch",
        lambda *_: {"cargo": "/verified/cargo", "python3": "/usr/bin/python3"},
    )
    monkeypatch.setattr(native, "runtime_identity", lambda _: {"inert": True})
    phases = []

    def run(argv, **kwargs):
        name = kwargs["out"].name
        phases.append(name)
        kwargs["attempt"].update(
            cleanupVerified=True,
            cleanup={"groupEmpty": True, "inspectionUnknown": False},
        )
        claimed = [r for r in state.requests(root) if r["state"] == "claimed"]
        if name == "resources":
            assert (
                len(claimed) == 1
                and claimed[0]["operation"] == "native-prepared-release"
            )
            (kwargs["out"] / "process.log").write_text(
                json.dumps(full_snapshot(target))
            )
        else:
            assert len(claimed) == 2 and len({r["id"] for r in claimed}) == 2
            assert {r["operation"]: r["amount"] for r in claimed} == {
                "native-prepared-release": 6 * 1024**3,
                "native-prepared-release-growth": extra,
            }
            assert (
                sum(r["outstanding"] for r in claimed)
                == full_snapshot(target)["reservationBytes"]
            )
        if name == "release":
            p = root / native.NATIVE / "target/release/openmates"
            p.parent.mkdir()
            p.write_bytes(binary())
            p.chmod(0o755)
        return 1 if fail_fetch and name == "fetch" else 0

    monkeypatch.setattr(lifecycle, "run_owned", run)
    if fail_fetch:
        with pytest.raises(native.Refused, match="build"):
            native.build(root, SOURCE, TREE, HARNESS)
        assert phases == ["resources", "fetch"]
    else:
        native.build(root, SOURCE, TREE, HARNESS)
        assert phases == ["resources", "fetch", "package-inputs", "release"]
    rows = state.requests(root)
    assert len(rows) == 2 and all(
        r["state"] == "complete" and r["outstanding"] == 0 for r in rows
    )
    assert [e for e in events if e[0] == "release"] == [
        ("release", "native-prepared-release-growth"),
        ("release", "native-prepared-release"),
    ]
    assert json.loads((root / native.BUILD_RECEIPT).read_text())["status"] == (
        "failed" if fail_fetch else "passed"
    )
