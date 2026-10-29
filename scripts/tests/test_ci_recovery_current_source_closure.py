# contract-test-file: tooling
"""Pure exact-current recovery source/Cargo/body and module closure controls.
Uses authentic reviewed source files as inputs to actual protected predicates.
Synthetic generated packages do not claim compiler, WASM or browser proof.
No subprocess, service, account or network operation is executed.
Original historical branches and import/module refusals remain required.
"""

from pathlib import Path
import json
import os
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import ci_rust_wasm as lane  # noqa: E402  # Requires the original sys.path bootstrap above.
from scripts import ci_metadata_rust_browser as metadata  # noqa: E402  # Requires the original sys.path bootstrap above.

SOURCE = "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478"
CARGO = "38a1e0eb7218dc52b3121d528b49411d481ef3a602e1e2d69e124520e3d3f441"
BODY = "1bdc2c5ed63001a8ebc06a79d29a2df60ef357840f4d993a55f96de69a57903b"


class CurrentRecoveryClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_root = Path(os.environ.get("OPENMATES_TEST_SOURCE_ROOT", ROOT))
        cls.source = (source_root / lane.SDK_SNIPPET_SOURCE).read_bytes()
        cls.cargo = (source_root / lane.SDK_PACKAGE_SOURCE).read_bytes()
        match = re.search(r'inline_js = "([\s\S]*?)"\)\]\s*extern', cls.source.decode())
        cls.body = json.loads(
            '"' + match[1].replace("\n", "\\n").replace("\r", "\\r") + '"'
        ).encode()
        cls.native = (source_root / metadata.NATIVE_SOURCE).read_bytes()

    def ordinary(self):
        sdk = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
        return (
            {
                "openmates_browser.js": (
                    'import * as import1 from "./'
                    + sdk
                    + '"\nexport function capture(){return import1.recoveryCapture();}'
                ).encode(),
                "openmates_browser_bg.wasm": b"\0asm\1\0\0\0",
                "openmates_browser.d.ts": b"export {};",
                sdk: self.body,
            },
            {lane.SDK_SNIPPET_SOURCE: SOURCE, lane.SDK_PACKAGE_SOURCE: CARGO},
            sdk,
        )

    def feature(self):
        crypto = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
        sdk = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
        native = "snippets/openmates-sdk-0123456789abcdef/src/platform/browser_metadata_native.js"
        files = {
            "openmates_browser.js": "".join(
                "import * as import" + str(i) + ' from "./' + name + '"\n'
                for i, name in enumerate((crypto, sdk, native), 1)
            ).encode()
            + b"export default function init(){};",
            "openmates_browser_bg.wasm": b"\0asm\1\0\0\0",
            "openmates_browser.d.ts": b"export {};",
            crypto: metadata.CRYPTO_BYTES,
            sdk: self.body,
            native: self.native,
        }
        return (
            files,
            {
                **metadata.SOURCE_PINS,
                metadata.RECOVERY_SOURCE: SOURCE,
                lane.SDK_PACKAGE_SOURCE: CARGO,
            },
            sdk,
        )

    def test_authentic_current_source_cargo_body_and_both_actual_package_predicates(
        self,
    ):
        self.assertEqual(
            (
                lane.sdk.sha(self.source),
                lane.sdk.sha(self.cargo),
                lane.sdk.sha(self.body),
                len(self.body),
            ),
            (SOURCE, CARGO, BODY, 4310),
        )
        files, inputs, _ = self.ordinary()
        self.assertEqual(lane.recovery_sdk_variant(SOURCE, CARGO), (BODY, 4310))
        self.assertIsNotNone(lane.recovery_sdk_output(files, inputs))
        self.assertTrue(lane.package_modules(files, inputs))
        files, inputs, _ = self.feature()
        self.assertTrue(
            metadata.package_modules(files, inputs, lane.closed_module_dependencies)
        )

    def test_old_exact_variants_and_old_metadata_source_policy_are_preserved(self):
        for cargo in (
            lane.SDK_PACKAGE_SOURCE_SHA256,
            lane.SDK_FLOAT_PACKAGE_SOURCE_SHA256,
        ):
            self.assertEqual(
                lane.recovery_sdk_variant(lane.SDK_SNIPPET_SOURCE_SHA256, cargo),
                (lane.SDK_SNIPPET_BODY_SHA256, lane.SDK_SNIPPET_BODY_BYTES),
            )
        self.assertEqual(
            lane.recovery_sdk_variant(
                metadata.SOURCE_PINS[metadata.RECOVERY_SOURCE], CARGO
            ),
            (BODY, 4310),
        )
        # This is the existing source-only metadata branch, not a new Cargo grant.
        self.assertTrue(
            metadata.recovery_source_bound(
                {
                    metadata.RECOVERY_SOURCE: metadata.SOURCE_PINS[
                        metadata.RECOVERY_SOURCE
                    ]
                }
            )
        )
        for cargo in (
            lane.SDK_PACKAGE_SOURCE_SHA256,
            lane.SDK_FLOAT_PACKAGE_SOURCE_SHA256,
            "0" * 64,
            None,
        ):
            self.assertIsNone(lane.recovery_sdk_variant(SOURCE, cargo))
            self.assertFalse(
                metadata.recovery_source_bound(
                    {metadata.RECOVERY_SOURCE: SOURCE, lane.SDK_PACKAGE_SOURCE: cargo}
                )
            )

    def test_changed_source_cargo_body_crosspair_and_extra_import_refusals(self):
        for feature in (False, True):
            for fault in (
                "source",
                "cargo",
                "body",
                "crosspair",
                "extraimport",
                "dynamic",
                "extrahelper",
            ):
                with self.subTest(feature=feature, fault=fault):
                    files, inputs, sdk = self.feature() if feature else self.ordinary()
                    if fault == "source":
                        inputs[lane.SDK_SNIPPET_SOURCE] = lane.sdk.sha(
                            self.source + b"changed"
                        )
                    elif fault == "cargo":
                        inputs[lane.SDK_PACKAGE_SOURCE] = lane.sdk.sha(
                            self.cargo + b"changed"
                        )
                    elif fault == "body":
                        files[sdk] += b"changed"
                    elif fault == "crosspair":
                        inputs[lane.SDK_PACKAGE_SOURCE] = (
                            lane.SDK_FLOAT_PACKAGE_SOURCE_SHA256
                        )
                    elif fault == "extraimport":
                        files["openmates_browser.js"] += b'\nimport "./unknown.js";'
                    elif fault == "dynamic":
                        files["openmates_browser.js"] += (
                            b'\nexport const p=import("./unknown.js");'
                        )
                    else:
                        files["unknown.js"] = b"export {};"
                    self.assertFalse(
                        metadata.package_modules(
                            files, inputs, lane.closed_module_dependencies
                        )
                        if feature
                        else lane.package_modules(files, inputs)
                    )

    def test_ordinary_namespace_and_unknown_export_guards_are_not_bypassed(self):
        for fragment in (
            b"import1.unknown();",
            b'import1["recoveryCapture"]();',
            b"const alias=import1;",
            b'import x from "./foreign.js";',
        ):
            files, inputs, _ = self.ordinary()
            files["openmates_browser.js"] += fragment
            self.assertFalse(lane.package_modules(files, inputs))


if __name__ == "__main__":
    unittest.main()
