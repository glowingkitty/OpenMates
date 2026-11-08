"""Pure finite helper tests. No docs/SDK/peer import, socket or subprocess."""

# contract-test-file: tooling
import ast
import hashlib
import json
import subprocess
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_contract import assert_python_contains  # noqa: E402 - sibling helper path set above

SOURCE = (Path(__file__).with_name("sdk-api-key-docs.py")).read_text()
A = SOURCE.index("# BEGIN CLOSED DOCS DIAGNOSTIC\n")
B = SOURCE.index("# END CLOSED DOCS DIAGNOSTIC")
SCOPE = {"hashlib": hashlib, "json": json, "subprocess": subprocess}
exec(
    compile(
        SOURCE[A + len("# BEGIN CLOSED DOCS DIAGNOSTIC\n") : B],
        "<pure-docs-diagnostic>",
        "exec",
    ),
    SCOPE,
)


class DocsDiagnosticTests(unittest.TestCase):
    def test_historical_source_hash_only_proves_generic_catch(self):
        out = SCOPE["decode_docs_digest"](
            35, "d1082c81df52fdcbd59e302f096450c000fc888536992b73d85c6faaca50cfc5"
        )
        self.assertEqual(
            out,
            {
                "status": "generic-only",
                "stage": "unclassified",
                "vector": "none",
                "error": "unclassified",
            },
        )

    def test_npm_child_line_is_finite_unique_and_never_raw_stderr(self):
        decode = SCOPE["docs_child"]
        line = b"npm docs diagnostic: stage=invoke;error=type\n"
        self.assertEqual(decode(b"PRIVATE_STACK_SECRET\n" + line), ("invoke", "type"))
        for value in [
            line + line,
            line + line + b"npm docs diagnostic: stage=sdk_import;error=syntax\n",
            line + b"npm docs diagnostic: stage=sdk_import;error=syntax\n",
            b"npm docs diagnostic: stage=PRIVATE;error=type\n",
            b"x" * 65537,
        ]:
            self.assertEqual(decode(value), ("none", "none"))

    def test_duplicate_a_plus_single_b_is_ambiguous_not_a_unique_b(self):
        a = b"npm docs diagnostic: stage=invoke;error=type\n"
        b = b"npm docs diagnostic: stage=sdk_import;error=syntax\n"
        self.assertEqual(SCOPE["docs_child"](a + a + b), ("none", "none"))
        self.assertEqual(SCOPE["docs_child"](a + b + b), ("none", "none"))
        self.assertEqual(SCOPE["docs_child"](b), ("sdk_import", "syntax"))

    def test_import_failures_and_unknown_process_failure_remain_suite_only(self):
        line = SCOPE["docs_line"]
        vector = SCOPE["DOCS_VECTOR_IDS"][0]
        for stage in [
            "arguments",
            "fixture_contract",
            "vector_admission",
            "peer_start",
            "adapter_launch",
        ]:
            self.assertIn(
                "vector=none;", line(stage, vector, "assertion", ("none", "none"))
            )
        self.assertIn(
            "vector=none;",
            line(
                "adapter_process",
                vector,
                "assertion",
                ("sdk_import", "module_not_found"),
            ),
        )
        self.assertIn(
            "vector=none;",
            line("adapter_process", vector, "assertion", ("none", "none")),
        )
        self.assertIn(
            "vector=" + vector + ";",
            line("response_assert", vector, "assertion", ("none", "none")),
        )
        self.assertNotIn(
            "PRIVATE", line("PRIVATE", "PRIVATE", "PRIVATE", ("PRIVATE", "PRIVATE"))
        )

    def test_closed_digest_decoder_matches_source_owned_line_without_generic_fallback(
        self,
    ):
        line = SCOPE["docs_line"](
            "adapter_process", "none", "assertion", ("sdk_import", "module_not_found")
        )
        raw = b"docs direct SDK conformance failed\n" + line.encode()
        out = SCOPE["decode_docs_digest"](len(raw), hashlib.sha256(raw).hexdigest())
        self.assertEqual(out["status"], "matched")
        self.assertEqual(out["vector"], "none")
        self.assertEqual(out["childStage"], "sdk_import")
        self.assertEqual(
            SCOPE["decode_docs_digest"](0, "0" * 64), {"status": "unmatched"}
        )

    def test_all_vectors_assertions_deadlines_credentials_cleanup_and_library_commands_preserved(
        self,
    ):
        self.assertEqual(len(SCOPE["DOCS_VECTOR_IDS"]), 31)
        self.assertEqual(len(set(SCOPE["DOCS_VECTOR_IDS"])), 31)
        # Formatting-independent: each statement/expression must still exist.
        assert_python_contains(
            SOURCE,
            "for v in vectors:",
            "vector['expected_request_count']*iterations",
            "observed['value']==vector['response']",
            "120 if c.get('iterations',1)>1 else 20",
            "os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=2)",
            "server.shutdown();server.server_close();thread.join(timeout=2)",
            "'sk-api-docsOwnerA.localSetupSuffix'",
            "return ['node',str(ROOT/'tests/sdk-conformance/runners/sdk-api-key-docs.mjs'),'--case']",
        )
        self.assertNotIn("--experimental-strip-types", SOURCE)
        assertions = sorted(
            ast.dump(node, include_attributes=False)
            for node in ast.walk(ast.parse(SOURCE))
            if isinstance(node, ast.Assert)
        )
        self.assertEqual(
            hashlib.sha256(json.dumps(assertions).encode()).hexdigest(),
            "dc44546d1f2033e36e087d75d920760e053a3723d741c99882c84f3099f454be",
        )
        ast.parse(SOURCE)


if __name__ == "__main__":
    unittest.main()
