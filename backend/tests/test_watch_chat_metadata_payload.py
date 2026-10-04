"""Encrypted Watch list metadata, without requiring a server or an account."""
import ast
from pathlib import Path
from typing import Any
import unittest


def serialize(chat):
    source = Path(__file__).parents[1] / "core/api/app/routes/chats.py"
    tree = ast.parse(source.read_text())
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name in {"_string_timestamp", "_watch_chat_payload"}]
    assert len(helpers) == 2
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_watch_chat_payload"](chat)


class WatchChatMetadataPayloadTests(unittest.TestCase):
    # contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    def test_encrypted_category_and_icon_survive_without_plaintext(self):
        result = serialize({"id": "synthetic-chat", "encrypted_category": "sealed-category",
                            "encrypted_icon": "sealed-icon", "category": "private-category",
                            "icon": "private-icon", "title": "private-title"})
        self.assertEqual(result["encrypted_category"], "sealed-category")
        self.assertEqual(result["encrypted_icon"], "sealed-icon")
        self.assertTrue({"category", "icon", "title"}.isdisjoint(result))

    # contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    def test_legacy_encrypted_alias_and_canonical_precedence(self):
        self.assertEqual(serialize({"encrypted_chat_category": "legacy-sealed"})["encrypted_category"],
                         "legacy-sealed")
        self.assertEqual(serialize({"encrypted_category": "canonical-sealed",
                                   "encrypted_chat_category": "legacy-sealed"})["encrypted_category"],
                         "canonical-sealed")

    # contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    def test_older_records_remain_compatible_and_metadata_is_optional(self):
        result = serialize({"id": "older", "encrypted_title": "sealed-title", "messages_v": 7})
        self.assertEqual(result["id"], "older")
        self.assertEqual(result["encrypted_title"], "sealed-title")
        self.assertIsNone(result["encrypted_category"])
        self.assertIsNone(result["encrypted_icon"])


if __name__ == "__main__":
    unittest.main()
