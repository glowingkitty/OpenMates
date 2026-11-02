"""Protected finite Workflow file dispatch. Never include this controller in SDK trust.

The pinned coordinator independently retires each WNOWAIT-reserved case group.
An interrupted/escalated run is failed; wrapper exit is no global drain proof.
"""

from __future__ import annotations
import json
import math
import os
import selectors
import subprocess
import sys
import time

try:
    from ci_sdk_share_dispatch import Cancellation, observed_exit, retire
except ModuleNotFoundError:
    from scripts.ci_sdk_share_dispatch import Cancellation, observed_exit, retire
try:
    from ci_sdk_conformance import (
        Refused,
        require,
        sha,
        verify_programs,
        compiler_diagnostics,
    )
except ModuleNotFoundError:
    from scripts.ci_sdk_conformance import (
        Refused,
        require,
        sha,
        verify_programs,
        compiler_diagnostics,
    )

CAPABILITY = "work.project-workflow-file-sync.v1"
FIXTURE = "tests/sdk-conformance/fixtures/workflow-file-sync.json"
LIMIT = 4 * 1024**2
EXPECTED_PLAN = [
    {
        "capability": "work.project-workflow-file-sync.v1",
        "fixture": "tests/sdk-conformance/fixtures/workflow-file-sync.json",
        "fixtureSha256": "f3dfa6c32f586f374c05f7fd667c04c27cf6b8fec1ae37a7f20f395e1e2bb056",
        "language": "rust",
        "vectors": [
            "ambiguous-team-scope",
            "apply-and-show",
            "approval-pending",
            "bad-after-hash",
            "cancel-held-result",
            "create-saved",
            "focus-mismatch",
            "foreign-item-scope",
            "invalid-approval-path",
            "metadata-denied",
            "no-auth",
            "pending-404-rotation",
            "privacy-denial",
            "remote-conflict",
            "remote-queued",
            "source-missing",
            "source-offline",
            "tuple-ack",
            "unapproved-exact-path",
            "unknown-404-no-retry",
            "update-saved",
            "version-race",
            "wrong-original-master",
        ],
    },
    {
        "capability": "work.project-workflow-file-sync.v1",
        "fixture": "tests/sdk-conformance/fixtures/workflow-file-sync.json",
        "fixtureSha256": "f3dfa6c32f586f374c05f7fd667c04c27cf6b8fec1ae37a7f20f395e1e2bb056",
        "language": "npm",
        "vectors": [
            "ambiguous-team-scope",
            "apply-and-show",
            "approval-pending",
            "bad-after-hash",
            "cancel-held-result",
            "create-saved",
            "focus-mismatch",
            "foreign-item-scope",
            "invalid-approval-path",
            "metadata-denied",
            "no-auth",
            "pending-404-rotation",
            "privacy-denial",
            "remote-conflict",
            "remote-queued",
            "source-missing",
            "source-offline",
            "tuple-ack",
            "unapproved-exact-path",
            "unknown-404-no-retry",
            "update-saved",
            "version-race",
            "wrong-original-master",
        ],
    },
    {
        "capability": "work.project-workflow-file-sync.v1",
        "fixture": "tests/sdk-conformance/fixtures/workflow-file-sync.json",
        "fixtureSha256": "f3dfa6c32f586f374c05f7fd667c04c27cf6b8fec1ae37a7f20f395e1e2bb056",
        "language": "python",
        "vectors": [
            "ambiguous-team-scope",
            "apply-and-show",
            "approval-pending",
            "bad-after-hash",
            "cancel-held-result",
            "create-saved",
            "focus-mismatch",
            "foreign-item-scope",
            "invalid-approval-path",
            "metadata-denied",
            "no-auth",
            "pending-404-rotation",
            "privacy-denial",
            "remote-conflict",
            "remote-queued",
            "source-missing",
            "source-offline",
            "tuple-ack",
            "unapproved-exact-path",
            "unknown-404-no-retry",
            "update-saved",
            "version-race",
            "wrong-original-master",
        ],
    },
]
# Fixed adapter inputs that must be present in the source under test.
PINS = (
    "frontend/packages/openmates-cli/src/sdk-session-v1-entry.ts",
    "frontend/packages/openmates-cli/src/sdkSession.ts",
    "frontend/packages/openmates-cli/tests/sdk-workflow-file-sync.test.mjs",
    "packages/openmates-python/openmates/__init__.py",
    "packages/openmates-python/openmates/session_client.py",
    "packages/openmates-python/tests/test_workflow_file_sync.py",
    "packages/openmates-rust/tests/fixtures/workflow-file-sync.json",
    "packages/openmates-session-bindings/examples/workflow-file-sync-conformance.rs",
    "packages/openmates-session-bindings/src/node.rs",
    "packages/openmates-session-bindings/src/python.rs",
    "packages/openmates-session-bindings/src/session.rs",
    "packages/openmates-session-bindings/src/session_work.rs",
    "packages/openmates-session-bindings/src/session_workflow_files.rs",
    "tests/sdk-conformance/fixtures/workflow-file-sync.json",
    "tests/sdk-conformance/runners/workflow-file-sync.mjs",
    "tests/sdk-conformance/runners/workflow-file-sync.py",
    "tests/sdk-conformance/schemas/workflow-file-sync.schema.json",
    "tests/sdk-conformance/session_workflow_files_peer.py",
    "tests/sdk-conformance/test_workflow_file_sync_peer.py",
    "frontend/packages/openmates-tui-native/Cargo.toml",
    "frontend/packages/openmates-tui-native/src/cli/workflows/files.rs",
    "frontend/packages/openmates-tui-native/src/cli/workflows/update.rs",
    "packages/openmates-rust/Cargo.toml",
    "packages/openmates-rust/src/work/workflows/file.rs",
    "packages/openmates-session-bindings/Cargo.toml",
    "tests/sdk-conformance/recovery_server.py",
    "tests/sdk-conformance/remote_crypto_peer.py",
    "tests/sdk-conformance/runners/session-embed-share.py",
    "frontend/packages/openmates-cli/tests/loader.mjs",
    "packages/openmates-rust/src/work/projects/workflow_files.rs",
)
PROTECTED_ONLY_INPUTS = frozenset({"frontend/packages/openmates-cli/tests/loader.mjs"})


def fixed_command(root, language):
    suffix = ["--fixture", str(root / FIXTURE), "--capability", CAPABILITY]
    if language == "rust":
        return [
            "cargo",
            "run",
            "--quiet",
            "--locked",
            "--manifest-path",
            "packages/openmates-session-bindings/Cargo.toml",
            "--example",
            "workflow-file-sync-conformance",
            "--",
            *suffix,
        ]
    if language == "npm":
        return ["node", "tests/sdk-conformance/runners/workflow-file-sync.mjs", *suffix]
    require(language == "python", "workflow_language")
    return [
        sys.executable,
        "tests/sdk-conformance/runners/workflow-file-sync.py",
        *suffix,
    ]


def admit(driver, command, *, cwd, capture_output, text, timeout, env, check):
    require(
        cwd == driver.root
        and capture_output is True
        and text is True
        and check is False,
        "driver_contract",
    )
    require(
        [row for row in driver.plan if row.get("capability") == CAPABILITY]
        == EXPECTED_PLAN,
        "workflow_plan",
    )
    index = len(driver.launches)
    require(index < len(driver.plan), "driver_count")
    identity = driver.plan[index]
    require(identity in EXPECTED_PLAN, "workflow_identity")
    require(
        command == fixed_command(driver.root, identity["language"])
        and command == driver.commands[index],
        "driver_order",
    )
    require(type(timeout) is int and timeout == 600, "workflow_timeout")
    require(
        type(driver.deadline) in (int, float)
        and math.isfinite(driver.deadline)
        and time.monotonic() < driver.deadline,
        "driver_deadline",
    )
    require(
        isinstance(env, dict)
        and env.get("OPENMATES_SDK_CONFORMANCE_PYTHON") == sys.executable
        and env.get("CARGO_INCREMENTAL") == "0",
        "workflow_environment",
    )
    verify_programs(driver.root, driver.trust)
    trusted = driver.trust["programs"] | driver.trust["contracts"]
    # Required inputs must exist; their bytes are whatever the source commit
    # holds (no per-file pins; the commit/ci-source identity is the authority).
    for name in PINS:
        path = driver.root / name
        require(name in PROTECTED_ONLY_INPUTS or (path.is_file() and not path.is_symlink()), "workflow_program_identity")
    require(
        not any(name.startswith("scripts/ci_sdk_") for name in trusted),
        "workflow_controller_self_trust",
    )
    return identity


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate workflow result field")
        value[key] = item
    return value


def validate_result(raw, identity):
    parsed = json.loads(raw, object_pairs_hook=unique)
    require(
        isinstance(parsed, dict)
        and set(parsed)
        == {"capability", "language", "fixtureSha256", "status", "results"}
        and parsed.get("capability") == CAPABILITY
        and parsed.get("language") == identity["language"]
        and parsed.get("fixtureSha256") == identity["fixtureSha256"]
        and parsed.get("status") == "passed",
        "driver_vector_result",
    )
    rows = parsed.get("results")
    require(
        isinstance(rows, list)
        and len(rows) == 23
        and all(
            isinstance(row, dict)
            and set(row) == {"id", "status"}
            and isinstance(row.get("id"), str)
            and row.get("status") == "passed"
            for row in rows
        )
        and len({row.get("id") for row in rows}) == 23
        and {row.get("id") for row in rows} == set(identity["vectors"]),
        "driver_vector_result",
    )


def run_workflow(
    driver, command, *, cwd, capture_output, text, timeout, env, check=False
):
    identity = admit(
        driver,
        command,
        cwd=cwd,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        env=env,
        check=check,
    )
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    child = selector = result = failure = None
    deadline = min(driver.deadline, time.monotonic() + timeout)
    driver.launches.append(
        {
            "capability": CAPABILITY,
            "language": identity["language"],
            "status": "started",
            "commandSha256": sha(json.dumps(command).encode()),
        }
    )
    # Register before Popen, including cancellation before its return/assignment.
    with Cancellation() as cancellation:
        try:
            cancellation.check()
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            cancellation.check()
            require(os.getpgid(child.pid) == child.pid, "share_group_ownership")
            selector = selectors.DefaultSelector()
            for name, channel in (("stdout", child.stdout), ("stderr", child.stderr)):
                selector.register(channel, selectors.EVENT_READ, name)
            exited_at = None
            while True:
                cancellation.check()
                now = time.monotonic()
                require(now < deadline, "driver_deadline")
                ended = observed_exit(child)
                if ended is not None:
                    exited_at = now if exited_at is None else exited_at
                    if not selector.get_map():
                        require(
                            ended.si_code == os.CLD_EXITED and ended.si_status == 0,
                            "driver_failed",
                        )
                        break
                    require(now - exited_at < 0.25, "share_descendant_pipes")
                for key, _ in selector.select(min(0.05, max(0, deadline - now))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        outputs[key.data].extend(chunk)
                        require(len(outputs[key.data]) <= LIMIT, "driver_output_bound")
            validate_result(outputs["stdout"], identity)
            verify_programs(driver.root, driver.trust)
            cancellation.check()
            result = subprocess.CompletedProcess(
                command,
                0,
                outputs["stdout"].decode("utf-8"),
                outputs["stderr"].decode("utf-8"),
            )
        except Exception as error:
            failure = error
        finally:
            try:
                if child is not None:
                    retire(child)
            except Exception as error:
                failure = error
            finally:
                if selector is not None:
                    selector.close()
                if child is not None:
                    for channel in (child.stdout, child.stderr):
                        if channel is not None:
                            channel.close()
            if cancellation.cancelled:
                failure = Refused("share_cancelled")
    if failure is None:
        try:
            require(
                result is not None and time.monotonic() < deadline, "driver_deadline"
            )
            verify_programs(driver.root, driver.trust)
        except Exception as error:
            failure = error
    if failure is not None:
        driver.failure = {
            "code": str(failure)
            if isinstance(failure, Refused)
            else "driver_unclassified",
            "adapter": {
                key: identity[key] for key in ("capability", "language", "vectors")
            },
            "returncode": child.returncode if child is not None else None,
            "terminatedReturncode": child.returncode if child is not None else None,
            "failedVectorIds": [],
            "stdoutBytes": len(outputs["stdout"]),
            "stderrBytes": len(outputs["stderr"]),
            "stdoutSha256": sha(outputs["stdout"]),
            "stderrSha256": sha(outputs["stderr"]),
            "compiler": compiler_diagnostics(
                outputs["stderr"], driver.root, driver.inputs
            ),
        }
        raise failure
    driver.launches[-1]["status"] = "passed"
    return result
