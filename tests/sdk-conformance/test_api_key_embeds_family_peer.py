"""Offline family protocol invariants and local-deadline evidence distinction."""

# contract-test-file: tooling
import json
from pathlib import Path
import unittest
from api_key_embeds_family_peer import EmbedsFamilyPeer


class FamilyPeerTests(unittest.TestCase):
    def setUp(self):
        self.suite = json.loads(
            (
                Path(__file__).parent / "fixtures/sdk-api-key-embeds-family.json"
            ).read_text()
        )["capabilities"]["sdk.embeds.family"]

    def vector(self, id):
        return next(v for v in self.suite["vectors"] if v["id"] == id)

    def test_local_deadline_has_semantic408_without_received_http_evidence(self):
        for lang in ("rust", "npm", "python"):
            peer = EmbedsFamilyPeer(
                self.suite, self.vector("preview-local-deadline"), lang
            )
            self.assertEqual(len(peer.sequence()), 1)
            peer.requests = 1
            correct = {
                "ok": False,
                "error": "preview-timeout",
                "timeout_source": "local",
                "semantic_status": 408,
                "http_observed": False,
            }
            peer.check(correct)
            for patch in (
                {"http_observed": True},
                {"timeout_source": "http"},
                {"semantic_status": 504},
            ):
                with self.assertRaises(AssertionError):
                    peer.check({**correct, **patch})

    def test_confirmation_refusal_and_exact_mutation_bodies(self):
        for lang in ("rust", "npm", "python"):
            peer = EmbedsFamilyPeer(
                self.suite, self.vector("restore-unconfirmed"), lang
            )
            self.assertEqual(peer.sequence(), [])
            peer.check({"ok": False, "error": "invalid"})
            peer = EmbedsFamilyPeer(self.suite, self.vector("restore-confirmed"), lang)
            headers = {
                "authorization": "Bearer sk-api-embedOwnerA",
                "x-openmates-sdk": {"rust": "rust", "npm": "npm", "python": "pip"}[
                    lang
                ],
                "x-openmates-device-identity": self.suite["device_id"],
            }
            method, path = peer.sequence()[0]
            body = None if lang == "npm" else {}
            self.assertEqual(peer.dispatch(method, path, headers, body)[0], 200)
            self.assertEqual(peer.dispatch(method, path, headers, body)[0], 400)

    def headers(self, lang):
        return {
            "authorization": "Bearer sk-api-embedOwnerA",
            "x-openmates-sdk": {"rust": "rust", "npm": "npm", "python": "pip"}[lang],
            "x-openmates-device-identity": self.suite["device_id"],
        }

    def test_selector_vectors_route_only_to_the_resolved_project(self):
        selectors = [v for v in self.suite["vectors"] if "resolved_project_id" in v]
        self.assertEqual(len(selectors), 7)
        listing = "/v1/projects?include_archived=true"
        for lang in ("rust", "npm", "python"):
            for v in selectors:
                with self.subTest(lang=lang, vector=v["id"]):
                    resolved = v["resolved_project_id"]
                    canonical = v["id"].endswith("canonical-uuid-unlisted")
                    peer = EmbedsFamilyPeer(self.suite, v, lang)
                    if not canonical:
                        status, body = peer.dispatch(
                            "GET", listing, self.headers(lang), None
                        )
                        self.assertEqual(status, 200)
                        self.assertEqual(len(body["projects"]), 3)
                    if resolved is None:
                        peer.check({"ok": False, "error": "invalid"})
                        continue
                    target = (
                        f"/v1/projects/{resolved}/items?item_type=embed"
                        f"&target_id={v['embed_id']}"
                    )
                    if v["operation"] == "remove_from_project":
                        self.assertEqual(
                            peer.dispatch("DELETE", target, self.headers(lang), None)[
                                0
                            ],
                            200,
                        )
                        peer.check({"ok": True, "value": v["response"]})
                    # Any other Project, or a second listing, is a refusal.
                    wrong = EmbedsFamilyPeer(self.suite, v, lang)
                    if not canonical:
                        wrong.dispatch("GET", listing, self.headers(lang), None)
                        self.assertEqual(
                            wrong.dispatch("GET", listing, self.headers(lang), None)[
                                0
                            ],
                            400,
                        )
                    other = EmbedsFamilyPeer(self.suite, v, lang)
                    self.assertEqual(
                        other.dispatch(
                            "DELETE",
                            "/v1/projects/22222222-2222-4222-8222-222222222222/items"
                            f"?item_type=embed&target_id={v['embed_id']}",
                            self.headers(lang),
                            None,
                        )[0],
                        400,
                    )
                    self.assertIsNotNone(other.failure)

    def test_selector_expectations_follow_npm_ranking(self):
        # Independent restatement of the npm reference: exact id, then
        # case-insensitive id prefix (>= 8 chars), then normalized slug, then
        # whitespace/case-normalized name; any ambiguous tier is refused.
        import re

        canonical = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
        )

        def slug(value):
            out = re.sub(r"[^a-z0-9]+", "-", value.strip().lower().replace("'", ""))
            return re.sub(r"-{2,}", "-", out).strip("-")[:80].rstrip("-")

        def rank(selector, projects):
            if canonical.fullmatch(selector):
                return selector
            exact = [p for p in projects if p["project_id"] == selector]
            if exact:
                return exact[0]["project_id"]
            tiers = (
                [
                    p
                    for p in projects
                    if len(selector) >= 8
                    and p["project_id"].lower().startswith(selector.lower())
                ],
                [p for p in projects if slug(p["slug"]) and slug(p["slug"]) == slug(selector)],
                [
                    p
                    for p in projects
                    if " ".join(p["name"].lower().split())
                    == " ".join(selector.lower().split())
                ],
            )
            for tier in tiers:
                if len(tier) > 1:
                    return None
                if tier:
                    return tier[0]["project_id"]
            return None

        for v in self.suite["vectors"]:
            if "resolved_project_id" in v:
                with self.subTest(vector=v["id"]):
                    self.assertEqual(
                        rank(v["project_id"], self.suite["selector_projects"]),
                        v["resolved_project_id"],
                    )

    def test_cookie_and_team_override_are_never_credentials(self):
        for lang in ("rust", "npm", "python"):
            for cookie, query in ((True, False), (False, True)):
                peer = EmbedsFamilyPeer(self.suite, self.vector("preview-status"), lang)
                headers = {
                    "authorization": "Bearer sk-api-embedOwnerA",
                    "x-openmates-sdk": {"rust": "rust", "npm": "npm", "python": "pip"}[
                        lang
                    ],
                    "x-openmates-device-identity": self.suite["device_id"],
                }
                if cookie:
                    headers["cookie"] = "ambient=wrong"
                method, path = peer.sequence()[0]
                self.assertEqual(
                    peer.dispatch(
                        method,
                        path + ("?team_id=alternate" if query else ""),
                        headers,
                        None,
                    )[0],
                    400,
                )


if __name__ == "__main__":
    unittest.main()
