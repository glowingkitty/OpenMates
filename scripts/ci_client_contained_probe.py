"""Finite existing-memory-lane contained kernel verification; no product acceptance."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import socket
import stat
import subprocess
import time

from scripts import ci_client_container_memory as memory_kernel
from scripts import ci_client_owned_lifecycle as owned_lifecycle
from scripts.ci_client_container_launch import Config, Launch, drain_complete_output, need
from scripts.ci_client_contained_meter import MeterSpec, elf_machine, validate_spec
from scripts.ci_client_memory_probe import SPEC, managed_gateway_id, verify_fixture

FLAGS = ["-O2", "-std=c11", "-Wall", "-Wextra", "-Werror"]
FROZEN = {
    "ci_client_contained_meter.py": "e8589f889c6345404fe2263ff57b08b43e146dcd15be5fa0ebe80c8d6304c291",
    "ci_client_container_launch.py": "61ed660cd0ffe0d3074e1ea8ecaf9f50d80eac763748b7e4be46dd4277c43daa",
    "ci_client_memory_supervisor.py": "69e4f7ae9d2e716f45ff3facd494ae8ac149c96fac619a4dfed157ebbf804b3f",
    "ci_client_process_memory_meter.c": "e11f0ecf008160ac3c8b296b2c00fbb0cbbad081871d0d736ee03f7319643acd",
    "ci_client_process_meter_original.c": "d21233cedd8954ab7e603b27d7d45f6b630b249581e799a7dd113dc13271ebd7",
}
CASES = ("leaf", "threads", "late-worker", "child", "clone3", "clone3-error", "clone3-untraced", "untraced", "node-threads", "long-lived", "crash", "cancel", "deadline", "controller-disconnect")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_compiler_cleanup(attempt):
    """An exited driver does not prove compiler descendants have drained."""
    cleanup = attempt.get("cleanup") or {}
    need(attempt.get("cleanupVerified") is True and cleanup.get("anchorHeld") is True
         and cleanup.get("liveMembersDrained") is True and cleanup.get("directChildReaped") is True
         and cleanup.get("inspectionUnknown") is False and cleanup.get("groupEmpty") is True,
         "compiler_group_cleanup_unverified")


def native_build(root, directory):
    """Use only the existing native compiler, no install/download or cross build."""
    compiler = shutil.which("cc")
    need(compiler is not None, "existing_native_compiler_required")
    compiler = Path(compiler).resolve(strict=True)
    info = compiler.stat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0 and os.access(compiler, os.X_OK), "readonly_system_compiler_required")
    compiler_hash = digest(compiler)
    need(elf_machine(compiler) == {"x86_64": 62, "aarch64": 183}.get(platform.machine()), "actual_native_compiler_required")
    need(Path(owned_lifecycle.__file__).resolve(strict=True) == root / "scripts/ci_client_owned_lifecycle.py", "subject_owned_lifecycle_required")
    directory.mkdir(mode=0o700, exist_ok=False)
    sources = {name: digest(root / "scripts" / name) for name in (*FROZEN, "ci_client_contained_fixture.c", "ci_client_owned_lifecycle.py")}
    need(all(sources[name] == value for name, value in FROZEN.items()), "reviewed_frozen_source_required")
    receipt = {"status": "build-started", "compilerPath": str(compiler), "compilerSha256": compiler_hash,
               "flags": FLAGS, "sourceSha256": {"process-memory-meter.c": sources["ci_client_process_memory_meter.c"], "process-meter-original.c": sources["ci_client_process_meter_original.c"]},
               "actualSources": sources, "nativeMachine": platform.machine(), "commands": [], "acceptanceEligible": False}
    receipt_path = directory / "preparation.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    for source, target, extra in (("ci_client_process_memory_meter.c", "process-memory-meter", []), ("ci_client_contained_fixture.c", "harmless-fixture", ["-pthread"])):
        binary = directory / target
        command = [str(compiler), *FLAGS, *extra, str(root / "scripts" / source), "-o", str(binary)]
        item = {"source": source, "argv": command, "status": "started"}
        receipt["commands"].append(item)
        stage = directory / (target + ".compile")
        stage.mkdir(mode=0o700, exist_ok=False)
        receipt["compilerLifecycleScope"] = "owned-inherited-process-group-detached-descendants-not-proven"
        try:
            code = owned_lifecycle.run_owned(command, cwd=root,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}, out=stage,
                    attempt={"kind": "strict-native-harmless-compiler", "source": source}, timeout=30)
            item["returncode"] = code
            owned_attempt = json.loads((stage / "attempt.json").read_bytes())
            verify_compiler_cleanup(owned_attempt)
            need(code == 0, "strict_native_build_failed")
            binary.chmod(0o500)
            need(elf_machine(binary) == elf_machine(compiler), "actual_native_elf_required")
            item.update(status="compiled-not-executed", sha256=digest(binary), machine=elf_machine(binary))
        finally:
            # Preserve actual failure output and raw unknown/zombie accounting.
            # Public copies contain only this fixed compiler/source diagnostic,
            # never application credentials or arbitrary workload output.
            for suffix, key in (("process.log", "compilerLog"), ("attempt.json", "ownedAttemptReceipt")):
                path = stage / suffix
                if path.is_file():
                    public = root / "test-results" / ("ci-contained-compiler-" + target + "." + suffix)
                    shutil.copyfile(path, public)
                    item[key] = {"path": public.relative_to(root).as_posix(), "sha256": digest(public), "bytes": public.stat().st_size}
                    if suffix == "attempt.json":
                        item["ownedAttempt"] = json.loads(path.read_bytes())
            receipt_path.write_text(json.dumps(receipt, indent=2))
    need(digest(compiler) == compiler_hash and all(digest(root / "scripts" / name) == value for name, value in sources.items()), "build_pins_changed")
    meter = directory / "process-memory-meter"
    receipt.update(status="built_pending_harmless_runtime_review", **{"process-memory-meterSha256": digest(meter)})
    receipt_path.write_text(json.dumps(receipt, indent=2))
    spec = MeterSpec(meter, digest(meter), sources["ci_client_process_memory_meter.c"], receipt_path, digest(receipt_path))
    validate_spec(spec, root)
    return spec, directory / "harmless-fixture", receipt


def terminal_line(proxy, expected, deadline):
    data = bytearray()
    selector = selectors.DefaultSelector()
    try:
        selector.register(proxy.stdout, selectors.EVENT_READ)
        while len(data) < 128 and time.monotonic() < deadline:
            if not selector.select(min(0.1, max(0.001, deadline - time.monotonic()))):
                continue
            byte = os.read(proxy.stdout.fileno(), 1)
            need(byte, "actual_phase_output_required")
            data += byte
            if byte == b"\n":
                need(data == expected, "finite_fixture_phase_required")
                return
        need(False, "actual_phase_deadline")
    finally:
        selector.close()


def evaluate(case, row):
    """No sampled/cgroup total peak; unavailable observations never pass positives."""
    need(row["cleanupVerified"] is True, "independent_cleanup_required")
    collection = row["collection"]
    need(collection.get("cleanupVerified") is True and collection.get("cleanupProblems") == [], "complete_container_cleanup_required")
    memory = collection.get("memory") or {}
    measured = memory.get("containedRss") or {}
    final = measured.get("final") or {}
    need(collection.get("metric") == "kernel-total-container-memory-not-rss", "charged_metric_label_required")
    if case == "controller-disconnect":
        need(row["exitCode"] != 0 and measured.get("status") != "observed" and measured.get("wholeApplicationPeakRssBytes") is None, "broken_final_channel_must_not_supply_rss")
        need(collection.get("code") is not None, "original_failed_collection_required")
        row["status"] = "verified-harmless-case"
        row["accountingUnavailable"] = "private-controller-deliberately-disconnected"
        return
    need(measured.get("authority") == "authenticated-pid1-private-channel", "original_private_final_authority_required")
    need(measured.get("acceptanceEligible") is False and measured.get("currentMigrationAcceptance") is False, "readiness_only")
    need(type(final.get("ownedShutdownConfirmed")) is bool, "explicit_wait_forest_status_required")
    if not (case == "clone3-untraced" and final.get("memoryStatus") == "missing-creation-event"):
        need(final["ownedShutdownConfirmed"] is True, "complete_wait_forest_required")
    need(measured.get("multiprocessTotalRss") == "unavailable-no-aggregation-or-subtraction", "multiprocess_gap_required")
    need(memory.get("chargedDiagnosticIncludes") == "common-pid1-plus-common-meter-plus-application", "charged_supervisor_scope_required")
    entries, events = final.get("containedClone3Entries"), final.get("containedClone3Events")
    need(type(entries) is int and type(events) is int and 0 <= events <= entries, "actual_clone3_counters_required")
    value = row.get("fixtureOutput")
    if case in ("leaf", "threads", "late-worker", "node-threads", "long-lived"):
        need(row["exitCode"] == 0 and measured.get("status") == "observed" and measured.get("wholeApplicationPeakRssBytes", 0) > 0 and final.get("processesEver") == 1, "complete_single_group_hwm_required")
        if case == "node-threads":
            verify_fixture(case, value)
            need(measured["wholeApplicationPeakRssBytes"] >= value["wholeFixturePeakRssKiB"] * 1024, "waited_hwm_covers_node_hwm")
        else:
            need(type(value) is dict and value.get("fixture") == case and value.get("privateFds") == 0 and value.get("acceptanceEligible") is False, "fixed_app_output_and_no_private_fds_required")
            need(measured["wholeApplicationPeakRssBytes"] >= value["selfRssKiB"] * 1024, "waited_hwm_covers_application_hwm")
        if case in ("threads", "late-worker", "node-threads"):
            need(final.get("threadCreates", 0) > 0, "actual_thread_identity_required")
        if case == "late-worker":
            need(value.get("lateWorker") is True and value.get("selfRssKiB", 0) >= 32 * 1024, "leader_zombie_before_late_allocation_required")
        if case == "long-lived":
            need(final.get("markerCount") == 10 and len(measured.get("rawLifecycleKernelSnapshots", [])) == 10 and measured.get("steadyRssBytes", 0) > 0 and measured.get("retainedRssBytes", 0) > 0, "actual_phase_counters_required")
    elif case == "child":
        need(row["exitCode"] == 0 and final.get("processesEver", 0) >= 2 and measured.get("status") == "unavailable" and measured.get("wholeApplicationPeakRssBytes") is None, "child_aggregate_must_remain_unavailable")
    elif case in ("clone3", "clone3-error", "clone3-untraced"):
        need(entries > 0, "real_clone3_entry_required")
        if events > 0:
            need(case == "clone3" and final.get("processesEver", 0) >= 2 and measured.get("status") == "unavailable" and measured.get("wholeApplicationPeakRssBytes") is None, "real_clone3_process_unavailable")
            row["clone3Outcome"] = "kernel-success-with-matching-event"
        elif final.get("memoryStatus") == "missing-creation-event":
            need(case == "clone3-untraced" and measured.get("status") == "unavailable" and measured.get("wholeApplicationPeakRssBytes") is None and row["exitCode"] != 0, "missing_event_must_refuse")
            row["clone3Outcome"] = "kernel-success-missing-event-refused"
        else:
            need(row["exitCode"] == 0 and value.get("syscallErrno", 0) > 0 and final.get("processesEver") == 1 and measured.get("status") == "observed", "genuine_kernel_error_only")
            row["clone3Outcome"] = "kernel-error-no-success-or-missing-event-proof"
            row["clone3Errno"] = value["syscallErrno"]
    else:
        reason = {"untraced": "untraced-clone-refused", "cancel": "cancelled", "deadline": "deadline"}.get(case)
        need(row["exitCode"] != 0 and measured.get("status") == "unavailable" and measured.get("wholeApplicationPeakRssBytes") is None, "negative_must_never_be_rss_success")
        if reason:
            need(final.get("memoryStatus") == reason, "exact_negative_reason_required")
        if case == "cancel":
            need(final.get("cancelObserved") == 1, "actual_meter_cancel_required")
        if case == "deadline":
            need(final.get("deadlineObserved") == 1, "actual_meter_deadline_required")
        if case == "crash":
            need(final.get("exitCode") == 139, "actual_fixture_crash_required")
    row["status"] = "verified-harmless-case"


class ProbeLaunch(Launch):
    """Read PID1 preflight only while actual bootstrap still has no app process."""
    gate_receipt = None

    def flag(self, name):
        if name == "go" and self.c.env.get("OPENMATES_CONTAINED_PREFLIGHT") == "1":
            need(self.contained is not None, "private_pid1_handshake_before_preflight_read")
            self.reader.recheck()
            fd = os.open("cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.reader.fd)
            try:
                memory_kernel.cgroup2_fd(fd)
                raw = os.read(fd, 65537)
                need(len(raw) <= 65536 and raw.split() == [str(self.reader.pid).encode()], "actual_pid1_only_preflight_boundary")
            finally:
                os.close(fd)
            value = json.loads((self.control / "negative-kernel-gates.json").read_bytes())
            need(type(value) is dict and len(value.get("cases", [])) == 7 and value.get("acceptanceEligible") is False, "finite_preflight_receipt_required")
            self.gate_receipt = {**value, "observationBoundary": "authenticated-pid1-only-before-go-no-application-fork"}
        return super().flag(name)


def execute_case(cfg, case, row):
    launch = ProbeLaunch(cfg)
    output = None
    try:
        proxy = launch.start(subprocess.PIPE if case == "long-lived" else subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE)
        if case == "controller-disconnect":
            launch.contained.sock.shutdown(socket.SHUT_RDWR)
        if case == "long-lived":
            try:
                launch.marker("steady", 2)
            except ValueError as error:
                need(str(error) == "finite_marker_sequence", "exact_out_of_order_marker_refusal")
                row["outOfOrderMarkerRefusedBeforeSend"] = True
            else:
                need(False, "out_of_order_marker_must_refuse")
            for phase, start in (("steady", 1), ("retained", 6)):
                terminal_line(proxy, (phase + "\n").encode(), cfg.work_deadline)
                for sequence in range(start, start + 5):
                    launch.marker(phase, sequence)
                proxy.stdin.write(b"x")
                proxy.stdin.flush()
            proxy.stdin.close()
        output = drain_complete_output(proxy, cfg.deadline)
        row.update(exitCode=output["exitCode"], complete=output["complete"], stdoutBytes=len(output["stdout"]), stderrBytes=len(output["stderr"]))
        if output["stdout"]:
            row["fixtureOutput"] = json.loads(output["stdout"])
    finally:
        if launch.bridge is not None and not launch.cleanup_started:
            row["collection"] = launch.finish()
        elif not launch.cleanup_started:
            launch.cleanup()
        row["cleanupVerified"] = launch.last_cleanup_result
        if launch.gate_receipt is not None:
            row["negativeKernelGates"] = launch.gate_receipt
    evaluate(case, row)
    return row


def run(root):
    from ci_environment import require_runner
    require_runner()
    need(os.environ.get("CI_TEST_MODE") == "e2e" and json.loads(os.environ.get("CI_SPECS_JSON", "[]")) == [SPEC], "exact_existing_memory_lane_required")
    from ci_runtime_images import runtime_key, verify_loaded_image
    from ci_run_tests import pinned_node, verify_pinned_node_runtime
    root = Path(root).resolve()
    context = json.loads((root / "test-results/ci-environment.json").read_bytes())
    source = context["source_commit"]
    need(re.fullmatch("[a-f0-9]{40}", source) and source == os.environ.get("BUILD_COMMIT_SHA") and context.get("run_id") == os.environ.get("GITHUB_RUN_ID"), "actual_managed_source_run_required")
    need(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=10).strip() == source, "actual_candidate_source_required")
    need(context.get("shared_dev_dns") == "rejected" and context.get("shared_dev_https") == "rejected" and context["services"]["api"]["running"] is True, "original_isolation_required")
    image = context["services"]["api"]["image"]
    key = runtime_key(root, "api")
    verify_loaded_image(root, "api", image, key)
    gateway = managed_gateway_id()
    verify_pinned_node_runtime()
    node = Path(pinned_node()).resolve(strict=True)
    result = {"kind": "contained-harmless-kernel-readiness", "status": "failed", "sourceCommit": source,
              "runId": context["run_id"], "acceptanceEligible": False, "currentMigrationAcceptance": False,
              "multiprocessTotalRss": "unavailable", "originalHost13": "preserved-separate-not-rerun-by-contained-probe", "cases": []}
    destination = root / "test-results/ci-client-contained-readiness.json"
    try:
        spec, fixture, preparation = native_build(root, root / "test-results/ci-private/contained-tools")
        result["nativeBuild"] = preparation
        private = root / "test-results/ci-private/client-memory/contained"
        private.mkdir(mode=0o700, exist_ok=False)
        supervisor = root / "scripts/ci_client_contained_probe_pid1.py"
        original = root / "scripts/ci_client_memory_supervisor.py"
        node_fixture = root / "scripts/ci_client_memory_fixture.mjs"
        for index, case in enumerate(CASES):
            state = private / case
            state.mkdir(mode=0o700)
            deadline = time.monotonic() + 23
            env = {"HOME": str(state), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
            if index == 0:
                env["OPENMATES_CONTAINED_PREFLIGHT"] = "1"
            cfg = Config(source_root=root, private_root=private, source=source, image=image, runtime_key=key,
                         gateway=gateway, owner="contained-readiness-" + context["run_id"], arm="rust", pair=index % 5 + 1,
                         argv=(str(node), str(node_fixture)) if case == "node-threads" else (str(fixture), "deadline" if case == "controller-disconnect" else case),
                         env=env, cwd=state, readonly_paths=(fixture, node_fixture, node, original), state_root=state,
                         conditions=(("image", image),), deadline=deadline, work_deadline=deadline - 12,
                         memory_limit=256 * 1024**2, pids_limit=32, cpus="1", uid=os.getuid(), gid=os.getgid(),
                         supervisor=supervisor, supervisor_sha256=digest(supervisor), max_application_seconds=3 if case == "deadline" else 10,
                         meter=replace(spec, lifecycle="long-lived") if case == "long-lived" else spec)
            row = {"case": case, "status": "failed", "acceptanceEligible": False}
            result["cases"].append(row)
            try:
                execute_case(cfg, case, row)
            except Exception as error:
                row["failureType"] = type(error).__name__
                row["failureCode"] = str(error)[:256]
                raise
            finally:
                destination.write_text(json.dumps(result, indent=2))
        result["status"] = "verified-harmless-cases"
        # Host policy is not weakened by runtime support in a private namespace.
        result["containedClone3Coverage"] = {row["case"]: row.get("clone3Outcome") for row in result["cases"] if row["case"].startswith("clone3")}
        outcomes = set(result["containedClone3Coverage"].values())
        required = {"clone3-success-event": "kernel-success-with-matching-event", "clone3-missing-event-refusal": "kernel-success-missing-event-refused"}
        result["unprovenKernelBranches"] = [name for name, outcome in required.items() if outcome not in outcomes]
        result["unprovenKernelBranches"].append("nonzero-capability-and-foreign-uid-runtime-refusal-no-privilege-grant")
        result["allSecurityRuntimeBranchesProven"] = False
    except Exception as error:
        result["failureType"] = type(error).__name__
        result["failureCode"] = str(error)[:256]
        raise
    finally:
        preparation_path = root / "test-results/ci-private/contained-tools/preparation.json"
        if preparation_path.exists():
            result["nativeBuild"] = json.loads(preparation_path.read_bytes())
        destination.write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
