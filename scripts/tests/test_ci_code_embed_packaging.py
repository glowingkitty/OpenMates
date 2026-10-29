# contract-test-file: tooling
"""Finite source/module predicate fixtures; no compiler/browser/native proof."""

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
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


def predicates():
    metadata = {"__name__": "exact_code_metadata_predicates"}
    exec(
        compile(
            (ROOT / "scripts/ci_metadata_rust_browser.py").read_bytes(),
            "exact_metadata_afterimage",
            "exec",
        ),
        metadata,
    )
    names = {
        "PACKAGE_NAME",
        "PACKAGE_FILES",
        "SNIPPET_PATH",
        "SNIPPET_SOURCE",
        "SNIPPET_SOURCE_SHA256",
        "SNIPPET_BYTES",
        "SDK_SNIPPET_PATH",
        "SDK_SNIPPET_SOURCE",
        "SDK_SNIPPET_SOURCE_SHA256",
        "SDK_SNIPPET_BODY_SHA256",
        "SDK_SNIPPET_BODY_BYTES",
        "SDK_PACKAGE_SOURCE",
        "SDK_PACKAGE_SOURCE_SHA256",
        "SDK_FLOAT_PACKAGE_SOURCE_SHA256",
        "SDK_FUNCTIONS",
        "MODULE_SPACE",
        "MODULE_LINES",
        "recovery_sdk_variant",
        "recovery_sdk_output",
        "_package_note",
        "package_names",
        "module_dependency_reason",
        "closed_module_dependencies",
        "package_import_headers",
        "package_modules",
    }
    lane = extract(
        ROOT / "scripts/ci_rust_wasm.py",
        names,
        {"re": re, "sdk": SimpleNamespace(sha=sha)},
    )
    return SimpleNamespace(**metadata), SimpleNamespace(**lane)


def inputs(m, cargo):
    return {**m.SOURCE_PINS, NATIVE: N, BRIDGE: B, RECOVERY: R, CARGO: cargo}


def fixture(m, cargo):
    raw = (ROOT / RECOVERY).read_text()
    found = re.search(r'inline_js = "([\s\S]*?)"\)\]\s*extern', raw)
    body = json.loads(
        '"' + found[1].replace("\n", "\\n").replace("\r", "\\r") + '"'
    ).encode()
    native = (ROOT / NATIVE).read_bytes()
    assert sha(native) == N and (sha(body), len(body)) == BODY
    c = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
    r = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
    n = "snippets/openmates-sdk-0123456789abcdef/src/platform/browser_metadata_native.js"
    files = {
        "openmates_browser.js": "".join(
            "import * as import" + str(i) + ' from "./' + path + '"\n'
            for i, path in enumerate((c, r, n), 1)
        ).encode()
        + b"export default function init(){};",
        "openmates_browser_bg.wasm": b"\0asm\x01\0\0\0",
        "openmates_browser.d.ts": b"export {};",
        c: m.CRYPTO_BYTES,
        r: body,
        n: native,
    }
    return files, inputs(m, cargo), (c, r, n)


class CodeEmbedPackagingTests(unittest.TestCase):
    def test_exact_two_variants_and_known_new_cross_pairs_cannot_fall_back(self):
        _, lane = predicates()
        for cargo in CARGOS:
            good = [R, cargo, N, B]
            self.assertEqual(lane.recovery_sdk_variant(*good), BODY)
            for index in range(4):
                for bad in (None, "", "0" * 64, OLD_N, OLD_B):
                    candidate = list(good)
                    candidate[index] = bad
                    self.assertIsNone(
                        lane.recovery_sdk_variant(*candidate), (cargo, index, bad)
                    )
            # The historical1cd/38a branch must not rescue either known-new half.
            self.assertIsNone(lane.recovery_sdk_variant(R, cargo, OLD_N, B))
            self.assertIsNone(lane.recovery_sdk_variant(R, cargo, N, OLD_B))

    def test_metadata_requires_all_components_and_preserves_original_pins(self):
        m, _ = predicates()
        for cargo in CARGOS:
            good = inputs(m, cargo)
            self.assertTrue(
                m.native_source_bound(good) and m.recovery_source_bound(good)
            )
            for name in (NATIVE, BRIDGE, RECOVERY, CARGO):
                for bad in (None, "", "0" * 64):
                    candidate = deepcopy(good)
                    if bad is None:
                        candidate.pop(name)
                    else:
                        candidate[name] = bad
                    self.assertFalse(
                        m.native_source_bound(candidate)
                        and m.recovery_source_bound(candidate),
                        (cargo, name, bad),
                    )
            for old in (OLD_N, m.SOURCE_PINS[NATIVE]):
                self.assertFalse(m.native_source_bound({**good, NATIVE: old}))
            self.assertFalse(m.native_source_bound({**good, BRIDGE: OLD_B}))
        self.assertTrue(m.native_source_bound(m.SOURCE_PINS))
        self.assertTrue(m.recovery_source_bound(m.SOURCE_PINS))

    def test_old_recovery_and_reply_tuple_branches_are_still_exact(self):
        m, lane = predicates()
        old_source = "fa3c9c6125b6a57ee1d2e98a800b034dbc8dc740da897e769c9780e775305fe3"
        old_body = (
            "f896283208ee2696872509a87d5256ec362ca8479ab24f410c6428322d5b3cbb",
            3365,
        )
        for cargo in (
            "adaf5d2b56d67875f101a4705db5538fd871f5146372be5721377c6b7c7582af",
            "cb7ab7ea51f6998304d921b238f8602a40fe342759e849f1e51caeef9d3a0f0f",
        ):
            self.assertEqual(lane.recovery_sdk_variant(old_source, cargo), old_body)
        self.assertEqual(
            lane.recovery_sdk_variant(m.SOURCE_PINS[RECOVERY], CARGOS[0]), BODY
        )
        self.assertEqual(lane.recovery_sdk_variant(R, CARGOS[0]), BODY)
        self.assertIsNone(lane.recovery_sdk_variant(R, CARGOS[1]))
        for cargo in CARGOS:
            self.assertEqual(lane.recovery_sdk_variant(R, cargo, OLD_N, OLD_B), BODY)
            old = {**inputs(m, cargo), NATIVE: OLD_N, BRIDGE: OLD_B}
            self.assertTrue(m.native_source_bound(old) and m.recovery_source_bound(old))

    def test_actual_metadata_module_guard_keeps_body_inventory_namespace_dependencies_closed(
        self,
    ):
        m, lane = predicates()
        for cargo in CARGOS:
            files, observed, snippets = fixture(m, cargo)

            def valid(f, i=observed):
                return m.package_modules(f, i, lane.closed_module_dependencies)

            self.assertTrue(valid(files))
            for name in snippets:
                self.assertFalse(
                    valid({**files, name: files[name] + b"changed"}), (cargo, name)
                )
            for name in (NATIVE, BRIDGE, RECOVERY, CARGO, m.CRYPTO_SOURCE):
                broken = dict(observed)
                broken.pop(name)
                self.assertFalse(valid(files, broken), (cargo, name))
            self.assertFalse(valid({**files, "unknown.js": b"export {};"}))
            self.assertFalse(
                valid(
                    {
                        **files,
                        snippets[2].replace(
                            "0123456789abcdef", "fedcba9876543210"
                        ): files[snippets[2]],
                    }
                )
            )
            for attack in (
                b'import("./foreign.js")',
                b'export * from "./foreign.js"',
                b'import "./foreign.js"',
                b'\\u0069mport("x")',
            ):
                self.assertFalse(
                    valid(
                        {
                            **files,
                            "openmates_browser.js": files["openmates_browser.js"]
                            + attack,
                        }
                    ),
                    attack,
                )
            changed = files["openmates_browser.js"].replace(
                b"import3 from", b"import2 from"
            )
            self.assertFalse(valid({**files, "openmates_browser.js": changed}))

    def test_actual_ordinary_recovery_guard_binds_body_and_closed_namespace(self):
        m, lane = predicates()
        for cargo in CARGOS:
            files, observed, (c, r, _) = fixture(m, cargo)
            ordinary = {
                name: value
                for name, value in files.items()
                if name in lane.PACKAGE_FILES or name in (c, r)
            }
            ordinary["openmates_browser.js"] = (
                'import * as import1 from "./'
                + c
                + '"\nimport * as import2 from "./'
                + r
                + '"\nexport function init(){return import2.recoveryRead();}'
            ).encode()
            self.assertTrue(lane.package_modules(ordinary, observed))
            self.assertFalse(
                lane.package_modules({**ordinary, r: ordinary[r] + b"x"}, observed)
            )
            for attack in (
                b"import2.foreign()",
                b'import2["recoveryRead"]()',
                b"const copy=import2;",
                b'import("./foreign.js")',
            ):
                self.assertFalse(
                    lane.package_modules(
                        {
                            **ordinary,
                            "openmates_browser.js": ordinary["openmates_browser.js"]
                            + attack,
                        },
                        observed,
                    ),
                    attack,
                )
            for name in (BRIDGE, NATIVE):
                broken = dict(observed)
                broken.pop(name)
                self.assertFalse(lane.package_modules(ordinary, broken), (cargo, name))

    def test_existing_full_source_collection_covers_new_modules_and_snapshot_refuses_drift(
        self,
    ):
        path = ROOT / "scripts/ci_sdk_lockfiles.py"
        policy = extract(path, {"ROOTS", "owned", "snapshot"}, {"Path": Path})
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
