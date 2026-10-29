# contract-test-file: tooling
"""Inert exact Workflow Cargo tuple controls; never compiler/runtime proof."""

import ast
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = "packages/openmates-rust/src/platform/browser_metadata_native.js"
BRIDGE = "packages/openmates-rust/src/platform/browser_metadata_native.rs"
RECOVERY = "packages/openmates-rust/src/platform/browser_recovery_port.rs"
CARGO = "packages/openmates-rust/Cargo.toml"
H = (
    "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478",
    "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6",
    "cf00e87ad951749f1c656af6f653dfac33f06c7d1b010883b60f19bf87ec044b",
    "fd9af1ccfc3c6fd1ebacf9e656140b821f5a5f5dd66a9a3eb97fdca007a91575",
)


def predicates():
    spec = importlib.util.spec_from_file_location(
        "workflow_metadata_predicates", ROOT / "scripts/ci_metadata_rust_browser.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    tree = ast.parse((ROOT / "scripts/ci_rust_wasm.py").read_bytes())
    names = {
        "SDK_SNIPPET_SOURCE_SHA256",
        "SDK_PACKAGE_SOURCE_SHA256",
        "SDK_FLOAT_PACKAGE_SOURCE_SHA256",
        "SDK_SNIPPET_BODY_SHA256",
        "SDK_SNIPPET_BODY_BYTES",
    }
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)
        or isinstance(n, ast.FunctionDef)
        and n.name == "recovery_sdk_variant"
    ]
    namespace = {}
    exec(
        compile(
            ast.Module(body=nodes, type_ignores=[]), "exact_maintained_variant", "exec"
        ),
        namespace,
    )
    return m, namespace["recovery_sdk_variant"]


class WorkflowCargoPackagingTests(unittest.TestCase):
    def test_variant_requires_every_exact_current_component(self):
        _, variant = predicates()
        expected = (
            "1bdc2c5ed63001a8ebc06a79d29a2df60ef357840f4d993a55f96de69a57903b",
            4310,
        )
        self.assertEqual(variant(*H), expected)
        self.assertIsNone(variant(*H[:2]))
        for index in range(4):
            for bad in (None, "0" * 64, "2610" + "0" * 60):
                values = list(H)
                values[index] = bad
                self.assertIsNone(variant(*values), (index, bad))
        for cargo in (
            "adaf5d2b56d67875f101a4705db5538fd871f5146372be5721377c6b7c7582af",
            "cb7ab7ea51f6998304d921b238f8602a40fe342759e849f1e51caeef9d3a0f0f",
        ):
            self.assertEqual(
                variant(
                    "fa3c9c6125b6a57ee1d2e98a800b034dbc8dc740da897e769c9780e775305fe3",
                    cargo,
                ),
                (
                    "f896283208ee2696872509a87d5256ec362ca8479ab24f410c6428322d5b3cbb",
                    3365,
                ),
            )

    def test_metadata_refuses_each_missing_changed_or_crossed_tuple(self):
        m, _ = predicates()
        inputs = {
            **m.SOURCE_PINS,
            RECOVERY: H[0],
            CARGO: H[1],
            NATIVE: H[2],
            BRIDGE: H[3],
        }
        self.assertTrue(m.recovery_source_bound(inputs))
        self.assertTrue(m.native_source_bound(inputs))
        for name in (RECOVERY, CARGO, NATIVE, BRIDGE):
            for bad in (None, "0" * 64):
                value = deepcopy(inputs)
                if bad is None:
                    value.pop(name)
                else:
                    value[name] = bad
                self.assertFalse(
                    m.recovery_source_bound(value) and m.native_source_bound(value),
                    (name, bad),
                )
        self.assertFalse(
            m.native_source_bound({**inputs, NATIVE: m.SOURCE_PINS[NATIVE]})
        )
        self.assertFalse(
            m.recovery_source_bound({**inputs, RECOVERY: m.SOURCE_PINS[RECOVERY]})
        )
        self.assertTrue(m.recovery_source_bound(m.SOURCE_PINS))
        self.assertTrue(m.native_source_bound(m.SOURCE_PINS))

    def test_optional_feature_source_stays_off_for_browser_and_default(self):
        import tomllib

        core = tomllib.loads((ROOT / CARGO).read_text())
        self.assertEqual(core["features"]["workflow-yaml"], ["dep:serde_yaml"])
        self.assertFalse(core["features"].get("default"))
        self.assertEqual(
            core["dependencies"]["serde_yaml"],
            {"package": "yaml_serde", "version": "=0.10.7", "optional": True},
        )
        browser = tomllib.loads(
            (ROOT / "packages/openmates-browser-bindings/Cargo.toml").read_text()
        )
        self.assertEqual(
            browser["features"],
            {
                "browser-metadata-prototype": [
                    "openmates-sdk/browser-metadata-prototype"
                ]
            },
        )
        self.assertNotIn(
            "features",
            browser["target"]['cfg(target_arch = "wasm32")']["dependencies"][
                "openmates-sdk"
            ],
        )
        self.assertEqual(hashlib.sha256((ROOT / CARGO).read_bytes()).hexdigest(), H[1])


if __name__ == "__main__":
    unittest.main()
