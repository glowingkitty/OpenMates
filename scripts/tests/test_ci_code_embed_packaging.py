# contract-test-file: tooling
"""Finite source/module predicate fixtures; no compiler/browser/native proof."""

import ast
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = "packages/openmates-rust/src/platform/browser_metadata_native.js"
BRIDGE = "packages/openmates-rust/src/platform/browser_metadata_native.rs"
RECOVERY = "packages/openmates-rust/src/platform/browser_recovery_port.rs"
CARGO = "packages/openmates-rust/Cargo.toml"
N = "2610b7f46fb61224dbaf405e3579a2b1ac95e90f7d28e9bfa095db6092289cf4"
B = "ca2814f2f7c8f12b0bcdf4ad92b8afd3b1aa923f08f503086a2075a8beb06e3c"
R = "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478"
CARGOS = (
    "38a1e0eb7218dc52b3121d528b49411d481ef3a602e1e2d69e124520e3d3f441",
    "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6",
)
BODY = ("1bdc2c5ed63001a8ebc06a79d29a2df60ef357840f4d993a55f96de69a57903b", 4310)
OLD_N = "cf00e87ad951749f1c656af6f653dfac33f06c7d1b010883b60f19bf87ec044b"
OLD_B = "fd9af1ccfc3c6fd1ebacf9e656140b821f5a5f5dd66a9a3eb97fdca007a91575"
# Existing full-root .rs collection already covers every new module; no list grant.
MODULES = (
    "packages/openmates-rust/src/client/browser_main_code_embed_policy.rs",
    "packages/openmates-rust/src/client/browser_main_code_embed_policy_tests.rs",
    "packages/openmates-rust/src/client/browser_main_code_embed_store.rs",
    "packages/openmates-rust/src/client/saved_embed_main_native.rs",
    "packages/openmates-rust/src/client/saved_embed_key_phases.rs",
    "packages/openmates-rust/src/client/saved_embed_owned.rs",
    "packages/openmates-rust/src/client/saved_embed_owned_tests.rs",
    "packages/openmates-browser-bindings/src/browser_recovery_code_embed.rs",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def extract(path, names, namespace):
    """Compile exact maintained AST nodes, with inert IO ports only where stated."""
    tree = ast.parse(path.read_bytes())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
        or isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id in names for t in node.targets)
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class CodeEmbedPackagingTests(unittest.TestCase):


    def test_existing_full_source_collection_covers_new_modules_and_snapshot_refuses_drift(
        self,
    ):
        path = ROOT / "scripts/ci_sdk_lockfiles.py"
        policy = extract(path, {"ROOTS", "WORKSPACE_FILES", "THIRD_PARTY", "SCOPES", "owned", "snapshot"}, {"Path": Path})
        for name in MODULES:
            self.assertTrue(policy["owned"](name), name)
        for name in (
            "scripts/ci_rust_wasm.py",
            "packages/openmates-rust/.cargo/config.toml",
            "packages/openmates-browser-bindings/../foreign.rs",
        ):
            self.assertFalse(policy["owned"](name), name)

        def require(value, _):
            if not value:
                raise ValueError("source")

        with TemporaryDirectory(prefix="inert-code-source-snapshot-") as temporary:
            root = Path(temporary)
            expected = {}
            for index, name in enumerate(MODULES):
                raw = ("inert-source-" + str(index)).encode()
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                expected[name] = sha(raw)
            names = "\0".join(MODULES).encode() + b"\0"

            def listing(argv, **_):
                self.assertEqual(
                    argv[:3],
                    ["git", "ls-files", "-z"]
                    if "--others" not in argv
                    else ["git", "ls-files", "--others"],
                )
                return b"" if "--others" in argv else names

            policy.update(
                subprocess=SimpleNamespace(check_output=listing),
                sdk=SimpleNamespace(
                    require=require, sha=sha, regular=lambda p: p.read_bytes()
                ),
            )
            self.assertEqual(policy["snapshot"](root, expected), expected)
            for name in MODULES:
                missing = dict(expected)
                missing.pop(name)
                with self.assertRaises(ValueError):
                    policy["snapshot"](root, missing)
                target = root / name
                raw = target.read_bytes()
                target.write_bytes(raw + b"drift")
                self.assertNotEqual(policy["snapshot"](root, expected), expected)
                target.write_bytes(raw)


if __name__ == "__main__":
    unittest.main()
