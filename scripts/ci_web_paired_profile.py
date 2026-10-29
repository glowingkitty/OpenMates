"""Exact, isolated startup pair producer; never accepts caller build receipts.

Both arms use the same checkout, account, backend, origin and browser settings.
The only build difference is the reviewed default-off Rust startup activation.
No timing/output acceptance is manufactured here: the real browser spec owns it.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import selectors
import shutil
import signal
import socket
import socketserver
import subprocess
import threading
import time
import sys
from urllib.request import urlopen

from ci_web_performance import (
    TOOL_SHA256,
    build_snapshot,
    digest,
    encoded,
    read_regular,
    reconcile_inventory,
    write_receipt,
)
from ci_sdk_conformance import terminate

SPEC = "web-essential-startup-performance.spec.ts"
ARMS = ("typescript", "rust")
DESTINATION = Path("target/ci-web-paired-profile")
MAX_OUTPUT = 16 * 1024**2
ORIGIN = "http://localhost:5173"
CASE_TITLE = "matched TypeScript and Rust essential startup preserves complete fixture outputs and paired latency floors"
# These are definitions of identical, real security settings, not SDK claims.
SECURITY = {
    "schemaVersion": 1,
    "origin": ORIGIN,
    "authentication": "real-ui-password-totp",
    "keyDerivation": "unchanged",
    "durability": "original-native-idb",
    "storageStateInjection": False,
    "networkInterception": False,
    "parentContentBudget": 20,
    "childContentOnDemand": True,
}
_CANCELLATION = ContextVar("paired_profile_cancellation", default=None)


def tooling_snapshot(harness):
    """Closed helper bytes must be the actual independently published harness.

    The workflow also checks them before this module's first import with a fresh
    Python bytecode cache. This is a held-file check, not a same-UID sandbox.
    """
    require(re.fullmatch(r"[a-f0-9]{40}", harness), "paired_harness_identity")
    tooling = Path(__file__).resolve().parents[1]
    clean = {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    actual = (
        subprocess.check_output(
            ["/usr/bin/git", "--no-replace-objects", "rev-parse", "HEAD"],
            cwd=tooling,
            env=clean,
            timeout=30,
        )
        .decode()
        .strip()
    )
    require(actual == harness, "paired_harness_identity")
    tree = subprocess.check_output(
        [
            "/usr/bin/git",
            "--no-replace-objects",
            "ls-tree",
            "-r",
            "-z",
            harness,
            "scripts",
        ],
        cwd=tooling,
        env=clean,
        timeout=30,
    )
    require(len(tree) <= 4 * 1024**2, "paired_tooling_tree_limit")
    expected = {}
    for row in tree.split(b"\0"):
        if not row:
            continue
        header, raw_name = row.split(b"\t", 1)
        mode, kind, oid = header.decode().split(" ")
        name = raw_name.decode("utf-8")
        if name.endswith(".py"):
            require(
                mode in {"100644", "100755"}
                and kind == "blob"
                and re.fullmatch(r"[a-f0-9]{40}", oid)
                and re.fullmatch(r"scripts/[A-Za-z0-9_./-]+\.py", name)
                and ".." not in Path(name).parts
            )
            expected[name] = oid
    require(1 <= len(expected) <= 4096, "paired_tooling_tree_limit")
    found = set()
    for directory, dirs, files in os.walk(tooling / "scripts", followlinks=False):
        require(
            all(not (Path(directory) / name).is_symlink() for name in dirs),
            "paired_tooling_shadow",
        )
        dirs[:] = [
            name for name in dirs if name != "__pycache__"
        ]  # fresh isolated cache is used by workflow
        for name in files:
            file = Path(directory) / name
            require(
                not file.name.endswith((".pyc", ".pyo", ".so", ".pyd")),
                "paired_tooling_shadow",
            )
            if name.endswith(".py"):
                found.add(file.relative_to(tooling).as_posix())
    require(found == set(expected), "paired_tooling_shadow")
    rows, total = {}, 0
    for name, oid in sorted(expected.items()):
        raw = read_regular(tooling / name, 4 * 1024**2)
        total += len(raw)
        require(
            total <= 64 * 1024**2
            and hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            == oid,
            "paired_tooling_changed",
        )
        rows[name] = digest(raw)
    return rows


def require(value, code="paired_profile_refused"):
    if not value:
        raise ValueError(code)


@contextmanager
def interruption_scope():
    """Defer signals until new children have owners; never interrupt cleanup."""
    state = {"requested": False}

    def interrupted(_number, _frame):
        state["requested"] = True

    old = {
        number: signal.getsignal(number)
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    }
    token = _CANCELLATION.set(state)
    try:
        for number in old:
            signal.signal(number, interrupted)
        yield state
    finally:
        for number, handler in old.items():
            signal.signal(number, handler)
        _CANCELLATION.reset(token)


def cancellation_checkpoint():
    state = _CANCELLATION.get()
    if state is not None and state["requested"]:
        raise InterruptedError("paired_interrupted")


def admission(ambient):
    require(
        all(
            ambient.get(k) == v
            for k, v in {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "OPENMATES_CI_ISOLATED": "1",
                "CI_TEST_MODE": "e2e",
            }.items()
        ),
        "paired_isolated_runner_required",
    )
    require(
        json.loads(ambient.get("CI_SPECS_JSON", "null")) == [SPEC],
        "paired_exact_selector_required",
    )
    require(not ambient.get("CI_PLAYWRIGHT_CASE_TITLE"), "paired_unfiltered_required")


def case_proof(report):
    """Exactly one original case, one real successful attempt; no retry/skip."""
    rows = []

    def visit(suites):
        for suite in suites:
            rows.extend(suite.get("specs", []))
            visit(suite.get("suites", []))

    visit(report.get("suites", []))
    if len(rows) != 1 or rows[0].get("title") != CASE_TITLE:
        return False
    tests = rows[0].get("tests", [])
    return (
        len(tests) == 1
        and tests[0].get("status") == "expected"
        and len(tests[0].get("results", [])) == 1
        and tests[0]["results"][0].get("status") == "passed"
        and tests[0]["results"][0].get("retry", 0) == 0
    )


def fixed_destination(root, *, fresh=False):
    destination = root / DESTINATION
    for path in (root / "target", destination):
        require(
            not path.is_symlink() and path.resolve() == path,
            "paired_unsafe_destination",
        )
    require(not fresh or not destination.exists(), "paired_existing_destination")
    return destination


def git_identity(root, ambient):
    def git(*args):
        return (
            subprocess.check_output(["git", *args], cwd=root, timeout=30)
            .decode()
            .strip()
        )

    source, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    require(
        re.fullmatch(r"[a-f0-9]{40}", source) and re.fullmatch(r"[a-f0-9]{40}", tree)
    )
    require(
        source == ambient.get("BUILD_COMMIT_SHA")
        and tree == ambient.get("CI_CANDIDATE_TREE"),
        "paired_source_identity",
    )
    return source, tree


def source_snapshot(root):
    """Actual tracked build inputs held across BOTH builds, including maintained generators.

    The isolated source unpacker establishes the Git tree. The ordinary workflow
    runs its UI/docs generators and Docker-config copy before this snapshot. We
    bind those actual inputs as well; neither arm may change any tracked input.
    """
    names = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root, timeout=30)
        .decode()
        .split("\0")
    )
    result = {}
    for name in names:
        cancellation_checkpoint()
        if name:
            require(not name.startswith("/") and ".." not in Path(name).parts)
            path = root / name
            # Git source symlinks are held as link targets, never followed.
            if path.is_symlink():
                result[name] = {"symlink": os.readlink(path)}
            else:
                raw = read_regular(path, 128 * 1024**2)
                result[name] = {"sha256": digest(raw), "bytes": len(raw)}
    return result


def owned_command(argv, *, root, env, timeout, limit=MAX_OUTPUT, check=True):
    """Fixed callers only; maintained TERM/KILL/reap, bounded BOTH streams.

    No shell, inherited stdin, unbounded capture or product output in exceptions.
    """
    held_tooling = (
        tooling_snapshot(env["CI_HARNESS_COMMIT"])
        if "CI_HARNESS_COMMIT" in env
        else None
    )
    child = subprocess.Popen(
        argv,
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector, data, sizes = selectors.DefaultSelector(), bytearray(), {}
    deadline = time.monotonic() + timeout
    try:
        cancellation_checkpoint()  # Popen returned; its new group is now owned.
        for stream in (child.stdout, child.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
            sizes[stream.fileno()] = 0
        while selector.get_map():
            cancellation_checkpoint()
            require(time.monotonic() < deadline, "paired_child_timeout")
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                sizes[key.fd] += len(chunk)
                require(sizes[key.fd] <= limit, "paired_child_output_limit")
                if key.fileobj is child.stdout:
                    data.extend(chunk)
        while child.poll() is None:
            cancellation_checkpoint()
            require(time.monotonic() < deadline, "paired_child_timeout")
            time.sleep(0.05)
        cancellation_checkpoint()
        if held_tooling is not None:
            require(
                held_tooling == tooling_snapshot(env["CI_HARNESS_COMMIT"]),
                "paired_tooling_changed",
            )
        if check:
            require(child.returncode == 0, "paired_child_failed")
            return bytes(data)
        return subprocess.CompletedProcess(argv, child.returncode)
    finally:
        selector.close()
        terminate(child)  # also cleans same-group descendants after leader success
        child.stdout.close()
        child.stderr.close()


def inventory(root, build, node, source):
    tool = read_regular(root / "scripts/web-production-asset-inventory.mjs", 128 * 1024)
    require(digest(tool) == TOOL_SHA256, "paired_inventory_tool")
    # The candidate tool is copied only after its maintained byte pin is checked.
    program = fixed_destination(root) / "inventory.mjs"
    if not program.exists():
        program.write_bytes(tool)
        program.chmod(0o600)
    require(read_regular(program, 128 * 1024) == tool)
    before = build_snapshot(build)
    raw = owned_command(
        [node, str(program), "--client-dir", str(build), "--source-commit", source],
        root=root,
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        timeout=120,
    )
    value = json.loads(raw)
    require(
        value.get("status") == "available" and value.get("sourceCommitClaim") == source
    )
    reconcile_inventory(value, before)
    require(before == build_snapshot(build), "paired_build_changed")
    return before, value


def clean_build_environment(ambient):
    return {
        k: v
        for k, v in ambient.items()
        if not k.startswith(
            (
                "OPENMATES_RUST_",
                "VITE_OPENMATES_RUST_",
                "OPENMATES_PERF_",
                "OPENMATES_PAIRED_",
            )
        )
    }


def build(root, ambient, node):
    admission(ambient)
    from ci_production_rust_browser import build_environment, verify_for_e2e

    source, tree = git_identity(root, ambient)
    tooling = tooling_snapshot(ambient.get("CI_HARNESS_COMMIT", ""))
    verify_for_e2e(root, environ=ambient)
    destination = fixed_destination(root, fresh=True)
    destination.mkdir(parents=True, mode=0o700)
    inputs = source_snapshot(root)
    output = root / "frontend/apps/web_app/build"
    receipts, held_snapshots = {}, {}
    for arm in ARMS:
        if output.exists():
            # Only the ordinary generated build directory, after strict held scan.
            build_snapshot(output)
            shutil.rmtree(output)
        env = clean_build_environment(ambient)
        env.update(
            OPENMATES_CI_PRECOMPRESS="0",
            VITE_API_URL="http://localhost:8000",
            VITE_ENV="self_hosted",
            VITE_UPLOAD_URL=ORIGIN,
        )
        if arm == "rust":
            env = build_environment(
                root,
                {
                    **env,
                    **verify_for_e2e(root, environ=ambient),
                },
            )
        owned_command(
            ["pnpm", "--dir", "frontend/apps/web_app", "exec", "vite", "build"],
            root=root,
            env=env,
            timeout=900,
        )
        require(inputs == source_snapshot(root), "paired_source_changed")
        verify_for_e2e(root, environ=ambient)
        held = destination / arm
        # Fresh generated output only. Original source tree is never copied.
        build_snapshot(output)
        shutil.copytree(output, held)
        snapshot, inv = inventory(root, held, node, source)
        inventory_hash = write_receipt(destination / f"{arm}-inventory.json", inv)
        receipt = {
            "schemaVersion": 1,
            "arm": arm,
            "sourceCommit": source,
            "sourceTree": tree,
            "harnessCommit": ambient["CI_HARNESS_COMMIT"],
            "toolingInputsSha256": digest(encoded(tooling)),
            "sourceInputsSha256": digest(encoded(inputs)),
            "buildTreeSha256": digest(encoded(snapshot)),
            "assetInventorySha256": inventory_hash,
            "inventoryToolSha256": TOOL_SHA256,
            "renderer": "adapter-static",
            "startupPrototype": arm == "rust",
            "buildEnvironment": {
                k: env[k]
                for k in (
                    "OPENMATES_CI_PRECOMPRESS",
                    "VITE_API_URL",
                    "VITE_ENV",
                    "VITE_UPLOAD_URL",
                )
            },
        }
        receipts[arm] = receipt
        held_snapshots[arm] = snapshot
        write_receipt(destination / f"{arm}-build.json", receipt)
    for arm in ARMS:
        require(
            build_snapshot(destination / arm) == held_snapshots[arm],
            "paired_previous_build_changed",
        )
        require(
            read_regular(destination / f"{arm}-build.json", 1024**2)
            == encoded(receipts[arm]),
            "paired_build_receipt_changed",
        )
        require(
            digest(read_regular(destination / f"{arm}-inventory.json", MAX_OUTPUT))
            == receipts[arm]["assetInventorySha256"],
            "paired_inventory_changed",
        )
    require(
        tooling == tooling_snapshot(ambient["CI_HARNESS_COMMIT"]),
        "paired_tooling_changed",
    )
    write_receipt(destination / "source-inputs.json", inputs)
    write_receipt(destination / "builds.json", {"schemaVersion": 1, "arms": receipts})


def validate_fixture(value):
    require(
        type(value) is dict and value.get("event") == "startup_performance_ready",
        "paired_fixture_event",
    )
    ids = [
        value.get("chatId"),
        *value.get("parentChatIds", []),
        *value.get("subchatIds", []),
    ]
    uuid = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
    require(
        len(ids) == 123
        and len(set(ids)) == 123
        and all(isinstance(x, str) and re.fullmatch(uuid, x) for x in ids)
    )
    require(
        re.fullmatch(uuid, value.get("ownerId", ""))
        and len(value["parentChatIds"]) == 120
        and len(value["subchatIds"]) == 2
        and len(value.get("subchatParentIds", [])) == 2
    )
    parents = value.get("contentParentIds", [])
    require(
        len(parents) == 20
        and len(set(parents)) == 20
        and set(parents) <= set(ids)
        and not set(parents).intersection(value["subchatIds"])
    )
    for key, expected in {
        "messageCount": 120,
        "inferenceCalls": 0,
        "metadataJobCount": 0,
        "selectedMessageCount": 6,
    }.items():
        require(type(value.get(key)) is int and value[key] == expected)
    for parent in parents:
        messages, plaintext = (
            value.get("contentMessageIds", {}).get(parent),
            value.get("contentPlaintext", {}).get(parent),
        )
        require(
            isinstance(messages, list)
            and len(messages) == len(set(messages)) == 6
            and all(isinstance(x, str) and re.fullmatch(uuid, x) for x in messages)
        )
        require(
            isinstance(plaintext, list)
            and len(plaintext) == 6
            and all(type(x) is str for x in plaintext)
        )
    return value


class Fixture:
    """One real CLI/CMS fixture process, retained until all ten arms close."""

    def __init__(self, root, node, env):
        self.child = subprocess.Popen(
            [
                node,
                "--experimental-strip-types",
                str(root / "scripts/ci_chat_metadata_recovery.mjs"),
                str(root),
                "--rust-browser-fixture",
            ],
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.events = queue.Queue(maxsize=8)
        self.closed = False
        self.cleanup_verified = False

        def read():
            try:
                while True:
                    line = self.child.stdout.readline(1024**2 + 1)
                    if not line:
                        break
                    require(len(line) <= 1024**2, "paired_fixture_output_limit")
                    event = json.loads(line)
                    self.events.put_nowait(event)
            except (ValueError, OSError, queue.Full):
                self.events.put_nowait(None) if not self.events.full() else None
            finally:
                if not self.events.full():
                    self.events.put_nowait(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            ready = self.next_event(45)
            require(
                type(ready) is dict and ready.get("event") == "ready",
                "paired_fixture_not_ready",
            )
            self.child.stdin.write(b"prepare-startup-performance\n")
            self.child.stdin.flush()
            self.value = validate_fixture(self.next_event(180))
            require(self.value["chatId"] == ready["chatId"])
        except BaseException:
            self.close()
            raise

    def next_event(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cancellation_checkpoint()
            try:
                return self.events.get(
                    timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                )
            except queue.Empty:
                pass
        raise ValueError("paired_fixture_timeout")

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.child.stdin.close()  # real fixture's finally deletes its CMS rows
            require(self.child.wait(timeout=30) == 0, "paired_fixture_cleanup_failed")
        finally:
            terminate(self.child)
            self.child.stdout.close()
            self.reader.join(timeout=3)
            require(not self.reader.is_alive(), "paired_fixture_reader_cleanup_failed")
        self.cleanup_verified = True


class Profile:
    """Private fixed-operation RPC; no caller paths, URLs, receipts or claims."""

    def __init__(self, root, results, node, env):
        admission(env)
        self.node = node
        self.server_env = {
            k: v
            for k, v in env.items()
            if not k.startswith("OPENMATES_TEST_ACCOUNT_")
            and k != "OPENMATES_STATE_DIR"
        }
        self.root, self.results, self.destination = (
            root,
            results,
            fixed_destination(root),
        )
        self.source, self.tree = git_identity(root, env)
        self.tooling = tooling_snapshot(env.get("CI_HARNESS_COMMIT", ""))
        producer = json.loads(
            read_regular(self.destination / "builds.json", 2 * 1024**2)
        )
        require(
            set(producer) == {"schemaVersion", "arms"}
            and producer["schemaVersion"] == 1
            and set(producer["arms"]) == set(ARMS)
        )
        self.rust_artifact = env.get("OPENMATES_RUST_CORE_ARTIFACT", "")
        self.inputs = json.loads(
            read_regular(self.destination / "source-inputs.json", 32 * 1024**2)
        )
        require(self.inputs == source_snapshot(root), "paired_source_changed")
        self.receipts, self.snapshots, self.served = {}, {}, {}
        self.active, self.position, self.closed = None, 0, False
        self.order = [
            (pair, arm)
            for pair in range(1, 6)
            for arm in (ARMS if pair % 2 else ARMS[::-1])
        ]
        self.web = self.web_thread = self.rpc = self.rpc_thread = self.fixture = None
        self.interruption = interruption_scope()
        self.interruption.__enter__()
        try:
            for arm in ARMS:
                snapshot, inv = inventory(
                    root, self.destination / arm, node, self.source
                )
                receipt = json.loads(
                    read_regular(self.destination / f"{arm}-build.json", 1024**2)
                )
                require(
                    receipt == producer["arms"][arm] and receipt["arm"] == arm,
                    "paired_producer_receipt",
                )
                require(
                    receipt["sourceCommit"] == self.source
                    and receipt["sourceTree"] == self.tree
                    and receipt["harnessCommit"] == env["CI_HARNESS_COMMIT"]
                    and receipt["toolingInputsSha256"] == digest(encoded(self.tooling))
                    and receipt["buildTreeSha256"] == digest(encoded(snapshot))
                    and receipt["sourceInputsSha256"] == digest(encoded(self.inputs))
                    and receipt["assetInventorySha256"]
                    == digest(
                        read_regular(
                            self.destination / f"{arm}-inventory.json", MAX_OUTPUT
                        )
                    )
                    and receipt["startupPrototype"] is (arm == "rust")
                )
                reconcile_inventory(inv, snapshot)
                self.receipts[arm], self.snapshots[arm] = receipt, snapshot
            # Real Playwright executable identity, produced by one fixed command.
            raw = owned_command(
                [
                    node,
                    "-e",
                    "const p=require('@playwright/test').chromium.executablePath();const c=require('node:child_process').execFileSync(p,['--version'],{encoding:'utf8',timeout:10000,maxBuffer:4096});process.stdout.write(JSON.stringify({path:p,version:c.match(/\\d+(?:\\.\\d+){2,3}/)[0]}));",
                ],
                root=root / "frontend/apps/web_app",
                env=clean_build_environment(env),
                timeout=30,
                limit=65536,
            )
            browser = json.loads(raw)
            executable = Path(browser["path"])
            require(
                executable.is_absolute()
                and re.fullmatch(r"[0-9.]{1,60}", browser["version"])
            )
            # Chromium binaries exceed the ordinary individual public asset bound.
            self.browser_sha = digest(read_regular(executable.resolve(), 512 * 1024**2))
            self.executable = executable.resolve()
            self.launch = {"headless": True, "executablePath": str(self.executable)}
            self.context = {
                "baseURL": ORIGIN,
                "viewport": {"width": 1280, "height": 720},
                "locale": "en-US",
                "timezoneId": "UTC",
                "colorScheme": "light",
            }
            settings = {
                "launch": self.launch,
                "context": {k: v for k, v in self.context.items() if k != "baseURL"},
                "browserVersion": browser["version"],
                "browserExecutableSha256": self.browser_sha,
            }
            # JS policy uses sorted canonical JSON without a trailing newline.
            settings_sha = digest(encoded(settings).rstrip(b"\n"))
            self.fixture = Fixture(root, node, env)
            fixture_sha = digest(encoded(self.fixture.value))
            oracle_sha = digest(
                encoded(
                    {
                        "seed": fixture_sha,
                        "physicalStores": [
                            "chats",
                            "messages",
                            "chat_compression_checkpoints",
                        ],
                        "oracle": "first-typescript-full-raw-phase-output-in-private-ram;independent-full-six-plaintext-and-id-predicates",
                        "seedSourceSha256": digest(
                            read_regular(
                                root / "scripts/ci_chat_metadata_recovery.mjs", 1024**2
                            )
                        ),
                    }
                )
            )
            security_sha = digest(encoded(SECURITY))
            profile = self
            for arm in ARMS:
                self.start_web(arm)
                try:
                    self.served[arm] = self.verify_served(arm)
                finally:
                    self.stop_web()
            self.active = None
            arms = {}
            for arm in ARMS:
                receipt_hash = write_receipt(
                    self.destination / f"{arm}-profile.json",
                    {
                        **self.receipts[arm],
                        "fixtureSha256": fixture_sha,
                        "fixtureOracleSha256": oracle_sha,
                        "settingsSha256": settings_sha,
                        "securityContractSha256": security_sha,
                        "servedBindingReceiptSha256": self.served[arm],
                    },
                )
                arms[arm] = {
                    "sourceCommit": self.source,
                    "sourceTree": self.tree,
                    "assetInventorySha256": self.receipts[arm]["assetInventorySha256"],
                    "servedBindingReceiptSha256": self.served[arm],
                    "profileReceiptSha256": receipt_hash,
                    "fixtureSha256": fixture_sha,
                    "settingsSha256": settings_sha,
                    "securityContractSha256": security_sha,
                }
            self.binding = {
                "schemaVersion": 1,
                "fixtureSha256": fixture_sha,
                "fixtureOracleSha256": oracle_sha,
                "settingsSha256": settings_sha,
                "securityContractSha256": security_sha,
                "startupParentBudget": 20,
                "parentMetadataCount": 121,
                "childMetadataCount": 2,
                "pairCount": 5,
                "browserVersion": browser["version"],
                "browserExecutableSha256": self.browser_sha,
                "arms": arms,
            }
            write_receipt(results / "ci-web-paired-profile.json", self.binding)
            retained = results / "paired-startup-profile"
            retained.mkdir(mode=0o700)
            for arm in ARMS:
                for kind in ("build", "inventory", "served", "profile"):
                    name = f"{arm}-{kind}.json"
                    raw = read_regular(self.destination / name, MAX_OUTPUT)
                    with (retained / name).open("xb") as stream:
                        os.fchmod(stream.fileno(), 0o600)
                        stream.write(raw)
            self.socket_path = self.destination / "profile.sock"
            require(not self.socket_path.exists())

            class RPC(socketserver.StreamRequestHandler):
                def handle(self):
                    self.connection.settimeout(10)
                    raw = self.rfile.readline(4097)
                    try:
                        require(raw.endswith(b"\n") and len(raw) <= 4096)
                        value = profile.dispatch(json.loads(raw))
                        self.wfile.write(encoded({"ok": True, "value": value}))
                    except (OSError, ValueError, KeyError, TypeError):
                        self.wfile.write(
                            encoded({"ok": False, "code": "paired_profile_refused"})
                        )

            self.rpc = socketserver.UnixStreamServer(str(self.socket_path), RPC)
            self.socket_path.chmod(0o600)
            self.socket_identity = self.socket_path.lstat().st_ino
            self.rpc_thread = threading.Thread(
                target=self.rpc.serve_forever, daemon=True
            )
            self.rpc_thread.start()
        except BaseException:
            self.close()
            raise

    def verify_served(self, arm):
        require(
            self.web is not None and self.web.poll() is None, "paired_server_failed"
        )
        require(self.inputs == source_snapshot(self.root), "paired_source_changed")
        require(
            self.snapshots[arm] == build_snapshot(self.destination / arm),
            "paired_build_changed",
        )

        def fetch(name):
            with urlopen(ORIGIN + "/" + name, timeout=10) as response:
                require(response.status == 200)
                raw = response.read(32 * 1024**2 + 1)
                require(len(raw) <= 32 * 1024**2)
                return raw

        index = fetch("index.html")
        require(
            digest(index) == self.snapshots[arm]["index.html"]["sha256"],
            "paired_served_index",
        )
        entries = sorted(
            set(re.findall(r"_app/immutable/entry/[A-Za-z0-9_.-]+\.js", index.decode()))
        )
        require(entries, "paired_served_entries")
        actual = {name: digest(fetch(name)) for name in entries}
        require(
            all(
                self.snapshots[arm].get(name, {}).get("sha256") == sha
                for name, sha in actual.items()
            )
        )
        require(self.web.poll() is None, "paired_server_failed")
        return write_receipt(
            self.destination / f"{arm}-served.json",
            {
                "schemaVersion": 1,
                "arm": arm,
                "sourceCommit": self.source,
                "sourceTree": self.tree,
                "origin": ORIGIN,
                "renderer": "adapter-static",
                "servedIndexSha256": digest(index),
                "servedEntrySha256": actual,
                "buildTreeSha256": digest(encoded(self.snapshots[arm])),
            },
        )

    def start_web(self, arm):
        require(arm in ARMS and self.web is None, "paired_previous_server_not_closed")
        # A pre-existing listener refuses. Never signal or replace its owner.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", 5173))
            except OSError as error:
                raise ValueError("paired_origin_already_owned") from error
        require(
            self.tooling == tooling_snapshot(self.server_env["CI_HARNESS_COMMIT"]),
            "paired_tooling_changed",
        )
        program = Path(__file__).resolve().with_name("ci_static_web.py")
        self.web = subprocess.Popen(
            [sys.executable, str(program), str(self.destination / arm)],
            cwd=self.root,
            env=self.server_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                cancellation_checkpoint()
                require(self.web.poll() is None, "paired_server_failed")
                try:
                    with socket.create_connection(("127.0.0.1", 5173), timeout=0.1):
                        return
                except OSError:
                    time.sleep(0.05)
            raise ValueError("paired_server_timeout")
        except BaseException:
            self.stop_web()
            raise

    def stop_web(self):
        if self.web is not None:
            child = self.web
            terminate(child)  # includes slow/partial HTTP request threads
            require(child.poll() is not None, "paired_server_cleanup_failed")
            self.web = None

    def dispatch(self, request):
        require(not self.closed and type(request) is dict)
        operation = request.get("operation")
        if operation == "describe":
            require(set(request) == {"operation"})
            return {
                "binding": self.binding,
                "launch": self.launch,
                "context": self.context,
                "fixture": self.fixture.value,
                "rustArtifact": self.rust_artifact,
                "served": {
                    arm: json.loads(
                        read_regular(self.destination / f"{arm}-served.json", 1024**2)
                    )
                    for arm in ARMS
                },
            }
        if operation == "activate":
            require(
                set(request) == {"operation", "arm", "pair"}
                and self.active is None
                and self.position < 10
                and type(request["pair"]) is int
                and (request["pair"], request["arm"]) == self.order[self.position]
            )
            arm = request["arm"]
            require(
                digest(read_regular(self.executable, 512 * 1024**2))
                == self.browser_sha,
                "paired_browser_changed",
            )
            self.active = arm
            try:
                self.start_web(arm)
                require(
                    self.verify_served(arm) == self.served[arm], "paired_served_changed"
                )
            except BaseException:
                self.stop_web()
                self.active = None
                raise
            return {
                "arm": arm,
                "pair": request["pair"],
                "servedBindingReceiptSha256": self.served[arm],
            }
        if operation == "release":
            require(
                set(request) == {"operation", "arm", "pair"}
                and self.active == request["arm"]
                and self.order[self.position] == (request["pair"], request["arm"])
            )
            require(self.verify_served(self.active) == self.served[self.active])
            self.stop_web()
            self.active = None
            self.position += 1
            return {"released": True}
        if operation == "close":
            require(set(request) == {"operation"})
            # Do not shutdown this RPC's own server thread from inside dispatch.
            self.active = None
            self.fixture.close()
            return {"fixtureClosed": True, "completedArms": self.position}
        raise ValueError("paired_fixed_operation_required")

    def environment(self):
        return {"OPENMATES_PAIRED_PROFILE_SOCKET": str(self.socket_path)}

    def run_browser(self, env):
        """The unchanged singleton Playwright argv/budget, in an owned group."""
        web = self.root / "frontend/apps/web_app"
        cli = web / "node_modules/@playwright/test/cli.js"
        require(cli.is_file() and cli.resolve().is_relative_to(self.root))
        argv = [
            self.node,
            str(cli),
            "test",
            "tests/" + SPEC,
            "--workers=1",
            "--reporter=json",
            "--output",
            "test-results/ci-0",
        ]
        return owned_command(argv, root=web, env=env, timeout=1200, check=False)

    def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        for server, thread in ((self.rpc, self.rpc_thread),):
            if server is not None:
                try:
                    server.shutdown()
                    server.server_close()
                    if thread is not None:
                        thread.join(timeout=3)
                        require(not thread.is_alive())
                except BaseException as error:
                    errors.append(error)
        try:
            self.stop_web()
        except BaseException as error:
            errors.append(error)
        if self.fixture is not None:
            try:
                self.fixture.close()
                require(self.fixture.cleanup_verified, "paired_fixture_cleanup_failed")
            except BaseException as error:
                errors.append(error)
        if hasattr(self, "socket_identity"):
            try:
                require(
                    self.socket_path.lstat().st_ino == self.socket_identity
                    and self.socket_path.is_socket()
                )
                self.socket_path.unlink()
            except BaseException as error:
                errors.append(error)
        if hasattr(self, "interruption"):
            self.interruption.__exit__(None, None, None)
        if hasattr(self, "results"):
            write_receipt(
                self.results / "ci-web-paired-cleanup.json",
                {
                    "schemaVersion": 1,
                    "status": "failed" if errors else "passed",
                    "sourceCommit": self.source,
                    "sourceTree": self.tree,
                    "completedArms": self.position,
                    "fixtureCleanupVerified": self.fixture is not None
                    and self.fixture.cleanup_verified,
                    "ownedListenersClosed": not errors,
                    "performanceAcceptance": False,
                },
            )
        if errors:
            raise ValueError("paired_cleanup_failed") from errors[0]


def main():
    import sys

    require(len(sys.argv) == 2 and sys.argv[1] == "build")
    root = Path(os.environ["OPENMATES_CI_SOURCE_ROOT"])
    with interruption_scope():
        build(root, os.environ, shutil.which("node") or "node")


if __name__ == "__main__":
    main()
