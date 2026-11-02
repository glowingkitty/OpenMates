"""Pure authored fixture/schema/peer/facade checks; never bind real sockets."""

# contract-test-file: tooling
import ast
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import jsonschema

ROOT = Path(
    os.environ.get("OPENMATES_SELECTED_SDK_ROOT", Path(__file__).resolve().parents[2])
)
BASE = Path(os.environ.get("OPENMATES_SELECTED_SDK_BASE", ROOT))
sys.path.insert(0, str(BASE / "tests/sdk-conformance"))
spec = importlib.util.spec_from_file_location(
    "selected_actual_peer", ROOT / "tests/sdk-conformance/essential_session_server.py"
)
peer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(peer_module)
FAMILY = "session.foreground-completion-recovery.v1"
FIXTURE = json.loads(
    (
        ROOT
        / "tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json"
    ).read_text()
)
SUITE = FIXTURE["capabilities"][FAMILY]
SCHEMA = json.loads(
    (
        ROOT
        / "tests/sdk-conformance/schemas/session-foreground-completion-recovery.schema.json"
    ).read_text()
)
OLD = [
    ("foreground-default-disabled", "disabled"),
    ("foreground-main-durable", "main"),
    ("foreground-one-byte-refusal", "main_byte"),
    ("foreground-ack-loss-resume", "main_lost_ack"),
    ("foreground-stage-reset", "main_reset"),
    ("foreground-claim-cancel", "main_cancel"),
    ("foreground-resume-owner-substitution", "main_owner"),
    ("foreground-expired-stage-reclaimed", "main_expiry"),
]


class ScriptedSocket:
    def __init__(self, identity, extra=()):
        self.frames = []
        self.events = [
            {
                "type": "native_client_lifecycle",
                "payload": {
                    "client_type": identity,
                    "interactive": False,
                    "is_foreground": True,
                },
            },
            *extra,
        ]
        self.handler = SimpleNamespace(
            connection=SimpleNamespace(settimeout=lambda _: None),
            essential_foreground_read=False,
        )

    def receive(self):
        return self.events.pop(0) if self.events else None

    def send(self, kind, payload):
        self.frames.append((kind, payload))

    def raw(self, *args):
        raise AssertionError("real wire forbidden")


class SelectedContract(unittest.TestCase):
    def peer(self, vector, identity):
        # Constructor crypto/sealing policy is real; only unused listener is replaced.
        with patch("recovery_server.ThreadingHTTPServer"):
            return peer_module.EssentialPeer(SUITE, vector, identity)

    def test_old_vectors_unchanged_and_new_schema_exact(self):
        self.assertEqual(SUITE["vectors"][:8], [{"id": i, "mode": m} for i, m in OLD])
        jsonschema.Draft202012Validator(SCHEMA).validate(FIXTURE)
        self.assertEqual(len(SUITE["vectors"]), 17)
        self.assertEqual(
            [row["mode"] for row in SUITE["vectors"][12:]],
            [
                "main_created_at",
                "main_cas_retry",
                "main_cas_exhausted",
                "selected_pending",
                "main_legacy_created_at",
            ],
        )

    def test_schema_rejects_missing_reordered_or_aliased_selection(self):
        for mutate in [
            lambda f: f["capabilities"][FAMILY]["vectors"].pop(),
            lambda f: f["capabilities"][FAMILY]["vectors"].reverse(),
            lambda f: f["capabilities"][FAMILY]["vectors"][8].update(chat_id="other"),
        ]:
            value = copy.deepcopy(FIXTURE)
            mutate(value)
            self.assertTrue(
                list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(value))
            )

    def test_actual_peer_startup_all3_exact_unrelated_offer_and_failure_modes(self):
        for identity in ("rust", "npm", "pip"):
            for vector in (
                row
                for row in SUITE["vectors"][8:]
                if row["mode"].startswith("selected_")
            ):
                with self.subTest(identity=identity, mode=vector["mode"]):
                    peer = self.peer(vector, identity)
                    transport = ScriptedSocket(identity)
                    peer.websocket(transport)
                    self.assertIsNone(peer.failure)
                    jobs = next(
                        p["jobs"]
                        for k, p in transport.frames
                        if k == "recovery_jobs_available"
                    )
                    self.assertEqual(
                        len(jobs),
                        1
                        if vector["mode"] in {"selected_empty", "selected_pending"}
                        else 2,
                    )
                    self.assertEqual(jobs[-1]["chat_id"], vector["unrelated_chat_id"])
                    self.assertEqual(jobs[-1]["job_id"], vector["unrelated_job_id"])
                    markers = [
                        p
                        for k, p in transport.frames
                        if k == "recovery_outputs_discovery_complete"
                    ]
                    self.assertEqual(
                        markers,
                        []
                        if vector["mode"] == "selected_cancel"
                        else [
                            {
                                "status": "failed"
                                if vector["mode"] == "selected_partial_failure"
                                else "completed"
                            }
                        ],
                    )
                    self.assertEqual(peer.counts["claims"], 0)
                    self.assertEqual(peer.counts["persists"], 0)

    def test_peer_refuses_global_sync_and_unrelated_claim_before_any_persistence(self):
        vector = SUITE["vectors"][8]
        for frame in [
            {"type": "phased_sync_request", "payload": {"phase": "all"}},
            {
                "type": "recovery_job_claim",
                "payload": {"job_id": vector["unrelated_job_id"]},
            },
        ]:
            peer = self.peer(vector, "rust")
            transport = ScriptedSocket("rust", [frame])
            peer.websocket(transport)
            self.assertIsNotNone(peer.failure)
            self.assertEqual(peer.counts["claims"], 0)
            self.assertEqual(peer.counts["persists"], 0)

    def test_actual_python_facade_delegates_exact_selection_without_cli_or_automatic_ack(
        self,
    ):
        source = ROOT / "packages/openmates-python/openmates/essential_session.py"
        tree = ast.parse(source.read_text())
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "SessionCompletionRecovery"
        )
        values = {"asyncio": asyncio, "json": json}
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__", names=[ast.alias(name="annotations")], level=0
                ),
                node,
            ],
            type_ignores=[],
        )
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), values)
        calls = []

        async def native(chat):
            calls.append(chat)
            return json.dumps([{"id": "opaque", "job": {"chat_id": chat}}])

        async def invoke(run):
            return await run()

        client = SimpleNamespace(
            _native=SimpleNamespace(completion_recovery_jobs_for_chat=native),
            _essential_call=invoke,
        )
        result = asyncio.run(
            values["SessionCompletionRecovery"](client).jobs_for_chat(
                SUITE["protocol"]["initial_chat_id"]
            )
        )
        self.assertEqual(calls, [SUITE["protocol"]["initial_chat_id"]])
        self.assertEqual(result[0]["id"], "opaque")

    def test_runner_dispatch_uses_real_all3_library_entrypoints(self):
        paths = {
            "packages/openmates-session-bindings/examples/support/selected_recovery.rs": "completion_recovery_jobs_for_chat",
            "tests/sdk-conformance/runners/selected-recovery.mjs": "recovery.jobsForChat",
            "tests/sdk-conformance/runners/selected_recovery.py": "recovery.jobs_for_chat",
        }
        for path, symbol in paths.items():
            text = (ROOT / path).read_text()
            self.assertIn(symbol, text)
            self.assertIn("unrelated-journal", text)
        script = (ROOT / "scripts/check_sdk_conformance.py").read_text()
        self.assertIn(
            '"tests/sdk-conformance/schemas/session-foreground-completion-recovery.schema.json"',
            script,
        )


# Execute the actual selected-only writer with an in-memory POSIX IO recorder.
# This proves ordering/refusal logic, not real OS or SDK durability.
class SelectedDurability(unittest.TestCase):
    def writer(self, *, owner=123, file_mode=0o600, corrupt=False):
        import stat
        from types import SimpleNamespace

        class IO:
            O_RDONLY = os.O_RDONLY
            O_RDWR = os.O_RDWR
            O_CREAT = os.O_CREAT
            O_EXCL = os.O_EXCL
            O_DIRECTORY = os.O_DIRECTORY
            O_NOFOLLOW = os.O_NOFOLLOW
            SEEK_SET = os.SEEK_SET

            def __init__(self):
                self.named = None
                self.handles = {}
                self.offset = 0
                self.events = []

            def geteuid(self):
                return 123

            def info(self, node):
                parent = node is None
                return SimpleNamespace(
                    st_uid=owner if parent else 123,
                    st_mode=(stat.S_IFDIR | 0o700)
                    if parent
                    else (stat.S_IFREG | file_mode),
                    st_dev=1,
                    st_ino=1 if parent else node["ino"],
                    st_nlink=1,
                    st_size=0 if parent else len(node["data"]),
                )

            def open(self, name, flags, mode=0, dir_fd=None):
                if str(name) == "/owned":
                    self.handles[1] = None
                    return 1
                if flags & self.O_CREAT:
                    assert self.named is None
                    self.named = {"ino": 2, "data": b""}
                assert self.named is not None
                self.handles[2] = self.named
                self.offset = 0
                return 2

            def fstat(self, fd):
                assert fd in self.handles
                return self.info(self.handles[fd])

            def lstat(self, name):
                return self.info(None if str(name) == "/owned" else self.named)

            def stat(self, name, dir_fd=None, follow_symlinks=False):
                assert dir_fd in self.handles
                return self.info(self.named)

            def write(self, fd, data):
                self.handles[fd]["data"] += data
                self.events.append("write")
                return len(data)

            def lseek(self, fd, offset, whence):
                assert fd in self.handles
                self.offset = offset
                return offset

            def read(self, fd, size):
                self.events.append("read")
                raw = self.handles[fd]["data"]
                data = (b"X" * len(raw) if corrupt else raw)[
                    self.offset : self.offset + size
                ]
                self.offset += len(data)
                return data

            def fsync(self, fd):
                assert fd in self.handles
                self.events.append("parent-sync" if fd == 1 else "file-sync")

            def close(self, fd):
                assert fd in self.handles
                self.events.append("close-" + str(fd))
                self.handles.pop(fd)

            def replace_path_same_bytes(self):
                old = self.named
                pinned = any(node is old for node in self.handles.values())
                self.named = {"ino": 3 if pinned else old["ino"], "data": old["data"]}

        source = ROOT / "tests/sdk-conformance/runners/selected_recovery.py"
        tree = ast.parse(source.read_text())
        names = {
            "_parent",
            "_current_parent",
            "_file",
            "read_selected",
            "write_selected",
            "close_selected",
        }
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        io = IO()
        scope = {"os": io, "stat": stat}
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
                str(source),
                "exec",
            ),
            scope,
        )
        return io, scope

    def test_selected_writer_file_and_parent_sync_precede_exact_readback_and_keep_fds_live(
        self,
    ):
        io, functions = self.writer()
        lease = functions["write_selected"](Path("/owned"), "checkpoint", b"exact")
        self.assertEqual(set(io.handles), {1, 2})
        self.assertLess(io.events.index("file-sync"), io.events.index("parent-sync"))
        self.assertLess(io.events.index("parent-sync"), io.events.index("read"))
        self.assertNotIn("close-2", io.events)
        self.assertEqual(
            functions["read_selected"](Path("/owned"), "checkpoint", b"exact", lease),
            b"exact",
        )
        functions["close_selected"](lease)
        functions["close_selected"](lease)
        self.assertEqual(io.handles, {})
        self.assertEqual(io.events.count("close-2"), 1)
        self.assertEqual(io.events.count("close-1"), 1)

    def test_open_writer_pins_inode_and_refuses_same_byte_path_replacement_or_closed_aba(
        self,
    ):
        io, functions = self.writer()
        lease = functions["write_selected"](Path("/owned"), "checkpoint", b"exact")
        self.assertEqual(io.fstat(lease["fd"]).st_ino, 2)
        io.replace_path_same_bytes()
        self.assertEqual(io.named["ino"], 3)
        with self.assertRaises(AssertionError):
            functions["read_selected"](Path("/owned"), "checkpoint", b"exact", lease)
        functions["close_selected"](lease)
        io.named = {
            "ino": 2,
            "data": b"exact",
        }  # numerical ABA after release grants nothing
        with self.assertRaises(AssertionError):
            functions["read_selected"](Path("/owned"), "checkpoint", b"exact", lease)
        self.assertEqual(io.handles, {})

    def test_runner_keeps_writer_leases_in_outer_finally_and_rust_owned_files(self):
        source = ROOT / "tests/sdk-conformance/runners/selected_recovery.py"
        tree = ast.parse(source.read_text())
        entry = next(
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "selected_recovery"
        )
        owner = next(n for n in entry.body if isinstance(n, ast.Try))
        self.assertTrue(owner.finalbody)
        self.assertTrue(
            any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "close_selected"
                for n in ast.walk(ast.Module(body=owner.finalbody, type_ignores=[]))
            )
        )
        rust = (
            ROOT
            / "packages/openmates-session-bindings/examples/support/selected_recovery.rs"
        ).read_text()
        self.assertIn("file:std::fs::File", rust)
        self.assertIn("parent:std::fs::File", rust)
        self.assertNotIn("drop(file);drop(parent)", rust)
        npm = (ROOT / "tests/sdk-conformance/runners/selected-recovery.mjs").read_text()
        self.assertIn("for(const entry of owned.reverse())", npm)
        self.assertIn("closeSelected(entry)", npm)

    def test_selected_writer_rejects_foreign_owner_nonprivate_mode_wrong_readback_and_closes_fds(
        self,
    ):
        for options in ({"owner": 999}, {"file_mode": 0o644}, {"corrupt": True}):
            io, functions = self.writer(**options)
            with self.assertRaises(AssertionError):
                functions["write_selected"](Path("/owned"), "checkpoint", b"exact")
            if not options.get("corrupt"):
                self.assertNotIn("parent-sync", io.events)
            self.assertEqual(io.handles, {})


if __name__ == "__main__":
    unittest.main()
