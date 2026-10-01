"""Developer-gallery fixture synchronization checks; no product rendering proof."""
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "apple/OpenMates/Sources/DevPreview/DevEmbedPreviewFixtures.swift"


class AppleEmbedGalleryFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = FIXTURES.read_text()
        literal = re.search(r'private static let webVariantJSON = #"""\n(.*?)\n    """#', source, re.S)
        if literal is None:
            raise AssertionError("Missing gallery variant snapshot")
        cls.snapshot = json.loads(literal.group(1))
        result = subprocess.run(
            ["node", "--disable-warning=ExperimentalWarning", "scripts/tests/helpers/apple_embed_gallery_web_variants.mjs"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        cls.web = json.loads(result.stdout)

    # contract-test: tooling
    def test_all_web_variant_payloads_and_showcase_labels_are_current(self):
        self.assertEqual(self.snapshot, self.web,
                         "Refresh the native snapshot from the mapped web preview modules.")

    # contract-test: tooling
    def test_every_registry_surface_has_an_explicit_variant_list(self):
        for surface in ("preview", "fullscreen"):
            self.assertGreater(len(self.snapshot[surface]), 80)
            for key, component in self.snapshot[surface].items():
                with self.subTest(surface=surface, key=key):
                    self.assertIn(component, self.snapshot["variants"])
                    names = [item["name"] for item in self.snapshot["variants"][component]]
                    self.assertEqual(len(names), len(set(names)))

    # contract-test: tooling
    def test_preview_and_fullscreen_keep_independent_real_code_payloads(self):
        preview = {v["name"]: v["props"] for v in self.snapshot["variants"][self.snapshot["preview"]["code-code"]]}
        fullscreen = {v["name"]: v["props"] for v in self.snapshot["variants"][self.snapshot["fullscreen"]["code-code"]]}
        self.assertEqual(preview["processing"]["status"], "processing")
        self.assertEqual(preview["python"]["filename"], "embed_service.py")
        long_code = fullscreen["longCode"]["data"]["decodedContent"]
        self.assertEqual(long_code["filename"], "long_file.py")
        self.assertEqual(len(long_code["code"].splitlines()), 100)
        self.assertNotIn("longCode", preview)

    # contract-test: tooling
    def test_named_empty_search_replaces_results_and_preserves_status(self):
        component = self.snapshot["preview"]["app:web:search"]
        variants = {v["name"]: v["props"] for v in self.snapshot["variants"][component]}
        for status in ("processing", "error", "cancelled"):
            self.assertEqual(variants[status]["results"], [])
            self.assertEqual(variants[status]["status"], status)


if __name__ == "__main__":
    unittest.main()
