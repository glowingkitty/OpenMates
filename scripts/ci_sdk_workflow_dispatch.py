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
        regular,
        sha,
        verify_programs,
        compiler_diagnostics,
    )
except ModuleNotFoundError:
    from scripts.ci_sdk_conformance import (
        Refused,
        require,
        regular,
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
PINS = {
    "frontend/packages/openmates-cli/src/sdk-session-v1-entry.ts": "b566ab14a40c6e91749d82536d252cb4d6336551b9173207f284e3ab2c4a0467",
    "frontend/packages/openmates-cli/src/sdkSession.ts": "cc833fbdcf75c2c0fa6c23c1588bdb09ad2a5126e22556b864f0998fb28a1a75",
    "frontend/packages/openmates-cli/tests/sdk-workflow-file-sync.test.mjs": "75675c075224a767a753c003fb3a46826f268813043d27158e1866bcd233b200",
    "packages/openmates-python/openmates/__init__.py": "ca8bbb0276aabcd897805dd7043dc2cde02d41334dde662a38d9490b4e23485d",
    "packages/openmates-python/openmates/session_client.py": "7f475259b25730c596704581fc44f9295af72b6fbfa0fda223d00d45bee5fdf2",
    "packages/openmates-python/tests/test_workflow_file_sync.py": "4854841d11f5a52a3003ffa379a0f0b827a52cfe0b219b5efca7b0cdbb622f2e",
    "packages/openmates-rust/tests/fixtures/workflow-file-sync.json": "f3dfa6c32f586f374c05f7fd667c04c27cf6b8fec1ae37a7f20f395e1e2bb056",
    "packages/openmates-session-bindings/examples/workflow-file-sync-conformance.rs": "3cf228af23ffded70f2270f269e1fbdc72039c8f27523a83dca20c1dfe91df6d",
    "packages/openmates-session-bindings/src/node.rs": "0ad8e9263a5ed863f51fa57973778628dd2e70f053dfbe8631a9dc2fd66b1f26",
    "packages/openmates-session-bindings/src/python.rs": "6b76ef2109bba0a4a354eceef39e637fd1df1a0a48a2938af2d9d2ecb00df2d2",
    "packages/openmates-session-bindings/src/session.rs": "10e3ed82e5ecee9165b9e63354b412279764cf6c92d6f8c00c7a755baaaffedc",
    "packages/openmates-session-bindings/src/session_work.rs": "a50409a830f8228ea2dfc6f577ca65b42bd8904ff57b464911b9670e56cc7f3c",
    "packages/openmates-session-bindings/src/session_workflow_files.rs": "460b46a1b7e983c6f162da2237c90c70d3191297297bdb4ddfc4c78221858b45",
    "tests/sdk-conformance/fixtures/workflow-file-sync.json": "f3dfa6c32f586f374c05f7fd667c04c27cf6b8fec1ae37a7f20f395e1e2bb056",
    "tests/sdk-conformance/runners/workflow-file-sync.mjs": "ee3d32c4f8ee8b0913460213a9e237fc500094994f89d5157cfc2fa5df2c3467",
    "tests/sdk-conformance/runners/workflow-file-sync.py": "aaa67bd5fadb47e171f407a81b19428583ab48f961c4de2d5b76db2d9f739fdc",
    "tests/sdk-conformance/schemas/workflow-file-sync.schema.json": "e28dfae4eda97f2923e96aa4b0f564f1981e29ff3e5b6f4aaec257e40746e17d",
    "tests/sdk-conformance/session_workflow_files_peer.py": "2b341941aff37b2dc68f046b1ccb0e4915abd23bf14901175b0013681c7995a9",
    "tests/sdk-conformance/test_workflow_file_sync_peer.py": "72e9135745a0eee39ca5ceaeed4af0f66257dbb136adb40c9358151e8dda12fe",
    "frontend/packages/openmates-tui-native/Cargo.toml": "40ce053c7f6c9415199f331d18c738ef5866c28a8684bf0dd3866ebfd0d0f7b4",
    "frontend/packages/openmates-tui-native/src/cli/workflows/files.rs": "6dfc6f0a2f33984382c92168d84322491e293febbd0dfc630b32e9a9fe795026",
    "frontend/packages/openmates-tui-native/src/cli/workflows/update.rs": "dc35153159642a29cc02b8b40ce4bf2fca093eedd2f4ccf8f55563f75e630389",
    "packages/openmates-rust/Cargo.toml": "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6",
    "packages/openmates-rust/src/work/workflows/file.rs": "bb876455397fef47edd652e93ce4e58bed7e42b614580a56b14e05a1e9363892",
    "packages/openmates-session-bindings/Cargo.toml": "4b46d12843f1d61d29833ac13b4e2e77cf1a307cc7db7db0a06a8bd344d7de1d",
    "tests/sdk-conformance/recovery_server.py": "5b6355ef2970619df7014fb6d4e8817b91efa52a0c6386982b6a7c5be6bcf743",
    "tests/sdk-conformance/remote_crypto_peer.py": "548db723f0c088761083fd928598a78d54b7be8770d31fac8b787bf9bcc8e775",
    "tests/sdk-conformance/runners/session-embed-share.py": "dab438b652149ec73d53e1e7360e598898c2d2b6a0415d3305140de81b0f2756",
    "frontend/packages/openmates-cli/tests/loader.mjs": "fd45c3652ada5bbca4abac145a5799cb3766b294fdfd0b4795cbb3fa67ec42d2",
    "packages/openmates-rust/src/work/projects/workflow_files.rs": "98e155e7a1e25e90940519d57e8cef2ee55c8b2aaa940df8a3120352f6a5aaf2",
}
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
    for name, digest in PINS.items():
        require(
            (name in PROTECTED_ONLY_INPUTS or trusted.get(name) == digest)
            and sha(regular(driver.root / name)) == digest,
            "workflow_program_identity",
        )
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
