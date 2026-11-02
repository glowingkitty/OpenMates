"""Inert guards for complete Python projection assertions in the real driver.

Only the two pure comparator function AST nodes are evaluated in this test.
No SDK module, peer server, credential or transport is imported/executed.
Every changed public field must fail; booleans never alias numeric counts.
Actual three-language runtime conformance remains a managed CI requirement.
"""

# contract-test-file: tooling
import ast
import copy
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parent
source = (ROOT / "runners/session-message-window.py").read_text()
tree = ast.parse(source)
helpers = [
    n
    for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name in {"exact", "assert_window"}
]
assert len(helpers) == 2
scope = {"copy": copy, "re": re}
exec(
    compile(
        ast.Module(body=helpers, type_ignores=[]), "<actual-driver-pure-guards>", "exec"
    ),
    scope,
)
SUITE = json.loads((ROOT / "fixtures/session-message-window.json").read_text())[
    "capabilities"
]["session.message-window.v1"]


def wire(vector):
    result = copy.deepcopy(vector["expected_public_paging"])
    result["chat"]["messages"] = copy.deepcopy(vector["expected_messages"])
    for name in ["startCursor", "endCursor", "oversizedMessageCursor"]:
        if result[name] is not None:
            result[name].update(chatId=SUITE["protocol"]["chat_id"], scope="a" * 64)
    return result


class DriverProjectionTests(unittest.TestCase):
    def test_every_success_literal_projection(self):
        for vector in SUITE["vectors"]:
            if vector["expected_error"] is None:
                scope["assert_window"](SUITE, vector, wire(vector))

    def test_every_public_field_identity_type_and_extra_key_mutation_refuses(self):
        vector = next(v for v in SUITE["vectors"] if v["mode"] == "latest")
        for name in vector["expected_public_paging"]:
            value = wire(vector)
            current = value[name]
            value[name] = (
                not current
                if type(current) is bool
                else current + 1
                if type(current) is int
                else current + "injected"
                if type(current) is str
                else {"unexpected": True}
            )
            with self.subTest(field=name), self.assertRaises(AssertionError):
                scope["assert_window"](SUITE, vector, value)
        for field, value in [
            ("chatId", "foreign"),
            ("scope", "PRIVATE"),
            ("createdAt", 0),
            ("messageId", "foreign"),
        ]:
            changed = wire(vector)
            changed["startCursor"][field] = value
            with self.subTest(cursor=field), self.assertRaises(AssertionError):
                scope["assert_window"](SUITE, vector, changed)
        for target in ["root", "chat", "cursor"]:
            changed = wire(vector)
            selected = (
                changed
                if target == "root"
                else changed["chat"]
                if target == "chat"
                else changed["startCursor"]
            )
            selected["extra"] = "arbitrary"
            with self.assertRaises(AssertionError):
                scope["assert_window"](SUITE, vector, changed)
        changed = wire(vector)
        changed["serverMessageCount"] = True
        with self.assertRaises(AssertionError):
            scope["assert_window"](SUITE, vector, changed)
        with self.assertRaises(AssertionError):
            scope["assert_window"](SUITE, vector, wire(vector), "b" * 64)

    def test_real_rust_driver_uses_whole_value_oracle_and_context(self):
        text = (
            ROOT.parent.parent
            / "packages/openmates-session-bindings/examples/session-message-window-conformance.rs"
        ).read_text()
        self.assertIn("check(page == &expected)?", text)
        self.assertIn("expected_scope.as_deref()", text)
        self.assertIn("assert_window(suite,latest,&first,None)?", text)


if __name__ == "__main__":
    unittest.main()
