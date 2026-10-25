"""Keep public example routes outside the deployed app-shell fallback."""

# contract-test-file: tooling

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class VercelPublicRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads((ROOT / "frontend/apps/web_app/vercel.json").read_text())
        fallback = [rule for rule in config["rewrites"] if rule["source"].startswith("/((?!")]
        assert len(fallback) == 1
        cls.app_shell = re.compile(f"^{fallback[0]['source']}$")

    def test_public_example_requests_reach_the_server_router(self):
        for path in (
            "/example", "/example/", "/example/retired-example",
            "/example/gigantic-airplanes-transporting-rocket-parts",
            "/example/retired-example/__data.json",
        ):
            with self.subTest(path=path):
                self.assertIsNone(self.app_shell.fullmatch(path))

    def test_private_client_routes_still_boot_the_app_shell(self):
        for path in ("/chats", "/settings", "/example-editor", "/projects/one"):
            with self.subTest(path=path):
                self.assertIsNotNone(self.app_shell.fullmatch(path))

    def test_other_public_assets_and_routes_keep_their_existing_routing(self):
        for path in (
            "/_app/immutable/start.js", "/landing", "/events/an-event",
            "/sitemap.xml", "/robots.txt", "/favicon.ico",
        ):
            with self.subTest(path=path):
                self.assertIsNone(self.app_shell.fullmatch(path))


if __name__ == "__main__":
    unittest.main()
