"""Protected finite share dispatch. Never include this controller in SDK trust.

The pinned coordinator independently retires each WNOWAIT-reserved case group.
An interrupted/escalated run is failed; wrapper exit is no global drain proof.
"""

from __future__ import annotations
import json
import math
import os
import selectors
import signal
import subprocess
import sys
import time

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

CAPABILITY = "session.embeds.admitted-share-url.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-embed-share-bindings.json"
LIMIT = 4 * 1024**2
TERM_GRACE = 1.5
REAP_GRACE = 0.5
EXPECTED_PLAN = [
    {
        "capability": "session.embeds.admitted-share-url.v1",
        "fixture": "tests/sdk-conformance/fixtures/session-embed-share-bindings.json",
        "fixtureSha256": "a1590a7b4983d2d82aa804ddba8b363a69d23ba72bc0f0cd8de79d8b3df3d84d",
        "language": "rust",
        "vectors": [
            "auth-owner-changed",
            "bad-tag",
            "direct-row",
            "expired-wrapper",
            "foreign-owner",
            "no-expiry",
            "noauth",
            "paired-expired",
            "password-sdk-not-cli-policy",
            "policy-denied",
            "signed-sdk-duration",
            "team",
            "team-row",
            "truncated",
            "wrong-key",
            "ws-denied",
        ],
    },
    {
        "capability": "session.embeds.admitted-share-url.v1",
        "fixture": "tests/sdk-conformance/fixtures/session-embed-share-bindings.json",
        "fixtureSha256": "a1590a7b4983d2d82aa804ddba8b363a69d23ba72bc0f0cd8de79d8b3df3d84d",
        "language": "npm",
        "vectors": [
            "auth-owner-changed",
            "bad-tag",
            "direct-row",
            "expired-wrapper",
            "foreign-owner",
            "no-expiry",
            "noauth",
            "paired-expired",
            "password-sdk-not-cli-policy",
            "policy-denied",
            "signed-sdk-duration",
            "team",
            "team-row",
            "truncated",
            "wrong-key",
            "ws-denied",
        ],
    },
    {
        "capability": "session.embeds.admitted-share-url.v1",
        "fixture": "tests/sdk-conformance/fixtures/session-embed-share-bindings.json",
        "fixtureSha256": "a1590a7b4983d2d82aa804ddba8b363a69d23ba72bc0f0cd8de79d8b3df3d84d",
        "language": "python",
        "vectors": [
            "auth-owner-changed",
            "bad-tag",
            "direct-row",
            "expired-wrapper",
            "foreign-owner",
            "no-expiry",
            "noauth",
            "paired-expired",
            "password-sdk-not-cli-policy",
            "policy-denied",
            "signed-sdk-duration",
            "team",
            "team-row",
            "truncated",
            "wrong-key",
            "ws-denied",
        ],
    },
]
PINS = {
    "tests/sdk-conformance/runners/session-embed-share.py": "dab438b652149ec73d53e1e7360e598898c2d2b6a0415d3305140de81b0f2756",
    "tests/sdk-conformance/runners/session-embed-share.mjs": "a6068005756f51760eeb0af842449567a28d7c6b60a6f38e70afc88fa6af76cd",
    "tests/sdk-conformance/session_embed_share_peer.py": "5e8deb5e4ae7dff1ac9d3fbd287cad50b088c0e0d2247e5b58beaff36524312c",
    "tests/sdk-conformance/session_drafts_server.py": "ee0f050b814a3b87a2799e29fc3a7ece0676a3e78e206857c80db940349e5baf",
    "tests/sdk-conformance/recovery_server.py": "5b6355ef2970619df7014fb6d4e8817b91efa52a0c6386982b6a7c5be6bcf743",
    "packages/openmates-session-bindings/examples/session-embed-share-conformance.rs": "db5277ad37fa371b476af2e7bbb54cdcd7800da54044287ad0c764fa38a5075c",
    "packages/openmates-session-bindings/src/session_embed_share.rs": "a8f1ef451e20767d7b63b4abe9bb260298d9b2f0b4bfb7d5e9a1f61c38bd2fb5",
    "frontend/packages/openmates-cli/tests/loader.mjs": "fd45c3652ada5bbca4abac145a5799cb3766b294fdfd0b4795cbb3fa67ec42d2",
    "frontend/packages/openmates-cli/src/sdkSession.ts": "cc833fbdcf75c2c0fa6c23c1588bdb09ad2a5126e22556b864f0998fb28a1a75",
    "packages/openmates-python/openmates/session_client.py": "7f475259b25730c596704581fc44f9295af72b6fbfa0fda223d00d45bee5fdf2",
    "tests/sdk-conformance/fixtures/session-embed-share-bindings.json": "a1590a7b4983d2d82aa804ddba8b363a69d23ba72bc0f0cd8de79d8b3df3d84d",
    "tests/sdk-conformance/schemas/session-embed-share-bindings.schema.json": "472fefda4ead2b1172f92d7d8c778046f473b413d43e1bdfcf4c7098bcbe47bc",
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
            "session-embed-share-conformance",
            "--",
            *suffix,
        ]
    if language == "npm":
        return [
            "node",
            "tests/sdk-conformance/runners/session-embed-share.mjs",
            *suffix,
        ]
    require(language == "python", "share_language")
    return [
        sys.executable,
        "tests/sdk-conformance/runners/session-embed-share.py",
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
        "share_plan",
    )
    index = len(driver.launches)
    require(index < len(driver.plan), "driver_count")
    identity = driver.plan[index]
    require(identity in EXPECTED_PLAN, "share_identity")
    require(
        command == fixed_command(driver.root, identity["language"])
        and command == driver.commands[index],
        "driver_order",
    )
    require(type(timeout) is int and timeout == 600, "share_timeout")
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
        "share_environment",
    )
    verify_programs(driver.root, driver.trust)
    trusted = driver.trust["programs"] | driver.trust["contracts"]
    for name, digest in PINS.items():
        require(
            (name in PROTECTED_ONLY_INPUTS or trusted.get(name) == digest)
            and sha(regular(driver.root / name)) == digest,
            "share_program_identity",
        )
    require(
        not any(name.startswith("scripts/ci_sdk_") for name in trusted),
        "share_controller_self_trust",
    )
    return identity


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate share result field")
        value[key] = item
    return value


def validate_result(raw, identity):
    parsed = json.loads(raw, object_pairs_hook=unique)
    require(
        isinstance(parsed, dict)
        and parsed.get("capability") == CAPABILITY
        and parsed.get("language") == identity["language"]
        and parsed.get("fixtureSha256") == identity["fixtureSha256"]
        and parsed.get("status") == "passed",
        "driver_vector_result",
    )
    rows = parsed.get("results")
    require(
        isinstance(rows, list)
        and len(rows) == 16
        and all(isinstance(row, dict) and row.get("status") == "passed" for row in rows)
        and len({row.get("id") for row in rows}) == 16
        and {row.get("id") for row in rows} == set(identity["vectors"]),
        "driver_vector_result",
    )


class Cancellation:
    def __init__(self):
        self.cancelled = False
        self.previous = {}

    def signal(self, _kind, _frame):
        self.cancelled = True

    def __enter__(self):
        for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            self.previous[kind] = signal.signal(kind, self.signal)
        return self

    def __exit__(self, *_):
        for kind, previous in self.previous.items():
            signal.signal(kind, previous)

    def check(self):
        require(not self.cancelled, "share_cancelled")


def observed_exit(child):
    return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)


def retire(child):
    # Popen(start_new_session=True) is the only group ownership issuer.
    # No poll()/wait() may release the leader before the final group signal.
    require(
        child.returncode is None and os.getpgid(child.pid) == child.pid,
        "share_group_ownership",
    )
    observed_exit(child)
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    # Cargo/Node can exit before the Python coordinator finishes its original
    # case-group finally. Keep the unreaped anchor and full bounded TERM grace,
    # even after wrapper exit; no poll/wait may release its PGID here.
    time.sleep(TERM_GRACE)
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=REAP_GRACE)


def run_share(driver, command, *, cwd, capture_output, text, timeout, env, check=False):
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
