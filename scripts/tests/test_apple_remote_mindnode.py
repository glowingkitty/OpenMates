#!/usr/bin/env python3
"""Isolated tests for the MindNode Apple Remote capability boundary.

Synthetic app bundles contain only public-style metadata and dictionaries.
These checks never connect to a Mac, launch MindNode or read personal maps.
Unsafe bundle links and malformed scripting dictionaries fail explicitly.
Native read/update support requires separate evidence from the actual Mac.
"""

# contract-test-file: infrastructure

import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "_apple_remote_mindnode.py"


def load_module():
    spec = importlib.util.spec_from_file_location("mindnode_remote", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "MindNode Classic.app"
        self.resources = self.app / "Contents/Resources"
        self.resources.mkdir(parents=True)
        self.info = {
            "CFBundleIdentifier": "test.mindnode",
            "CFBundleShortVersionString": "1.2.3",
            "NSScriptingDefinition": "MindNode.sdef",
            "CFBundleDocumentTypes": [{"LSItemContentTypes": ["test.mindnode.document"]}],
        }
        self.write_info()
        (self.resources / "MindNode.sdef").write_text(
            '<dictionary><suite name="MindNode"><class name="node" code="node">'
            '<property name="id" code="ID  " access="r"/>'
            '<property name="title" code="titl" access="rw"/>'
            '</class><command name="save" code="coresave"/></suite></dictionary>'
        )

    def write_info(self):
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))

    def test_public_dictionary_report_does_not_claim_native_write_support(self):
        result = self.module.discover_capabilities([self.root])
        self.assertTrue(result["ok"])
        app = result["apps"][0]
        self.assertEqual(app["version"], "1.2.3")
        self.assertEqual(app["scripting"]["status"], "dictionary_present")
        self.assertIn('name="title"', app["scripting"]["xml"])
        self.assertFalse(result["native_round_trip_verified"])
        self.assertFalse(result["write_enabled"])

    def test_missing_app_is_explicit(self):
        empty = self.root / "empty"
        empty.mkdir()
        result = self.module.discover_capabilities([empty])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mindnode_not_found")

    def test_missing_dictionary_is_not_assumed_scriptable(self):
        del self.info["NSScriptingDefinition"]
        self.write_info()
        result = self.module.discover_capabilities([self.root])
        self.assertEqual(result["apps"][0]["scripting"]["status"], "not_declared")

    def test_dictionary_path_traversal_is_rejected(self):
        self.info["NSScriptingDefinition"] = "../../private.sdef"
        self.write_info()
        result = self.module.discover_capabilities([self.root])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unsafe_bundle_path")

    def test_dictionary_symlink_is_rejected(self):
        other = self.root / "private.txt"
        other.write_text("private sentinel")
        self.info["NSScriptingDefinition"] = "linked.sdef"
        self.write_info()
        (self.resources / "linked.sdef").symlink_to(other)
        result = self.module.discover_capabilities([self.root])
        self.assertEqual(result["error"]["code"], "unsafe_bundle_path")
        self.assertNotIn("private sentinel", str(result))

    def test_external_entity_dictionary_is_rejected(self):
        (self.resources / "MindNode.sdef").write_text(
            '<!DOCTYPE dictionary [<!ENTITY private SYSTEM "file:///private">]>'
            '<dictionary>&private;</dictionary>'
        )
        result = self.module.discover_capabilities([self.root])
        self.assertEqual(result["error"]["code"], "unsupported_dictionary")

    def test_oversize_dictionary_is_rejected(self):
        (self.resources / "MindNode.sdef").write_bytes(b"x" * (self.module.MAX_METADATA_BYTES + 1))
        result = self.module.discover_capabilities([self.root])
        self.assertEqual(result["error"]["code"], "metadata_too_large")


if __name__ == "__main__":
    unittest.main()
