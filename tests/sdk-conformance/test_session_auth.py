"""Fixture derivation and transcript matcher checks; no product transport."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import struct
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = load("session_auth_generator", HERE / "generate_session_auth.py")
RUNNER = load("session_auth_runner", HERE / "runners/session-auth.py")


class SessionAuthFixtureTests(unittest.TestCase):
    def test_checked_in_fixture_is_reproducible_from_public_constants(self):
        expected = json.dumps(GENERATOR.build(), indent=2) + "\n"
        self.assertEqual((HERE / "fixtures/session-auth.json").read_text(), expected)

    def test_proofs_bind_independent_nonce_and_otp_uses_rfc_public_key(self):
        fixture = GENERATOR.build()
        known = json.loads(GENERATOR.SOURCE.read_text())
        auth = base64.urlsafe_b64decode(known["auth_key_v2"] + "=")
        for vector in fixture["capabilities"][RUNNER.CAPABILITY]["vectors"]:
            otp = vector["totp"]
            counter = otp["unix_seconds"] // otp["period"]
            digest = hmac.new(
                base64.b32decode(otp["secret_b32"]),
                struct.pack(">Q", counter),
                hashlib.sha1,
            ).digest()
            offset = digest[-1] & 15
            integer = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
            self.assertEqual(otp["code"], f"{integer % 10 ** otp['digits']:06d}")
            challenges = {}
            for step in vector["steps"]:
                if step["path"] == "/v1/auth/password-v2/challenge":
                    response = step["response"]["json"]
                    nonce = base64.urlsafe_b64decode(response["nonce"] + "=")
                    self.assertNotIn(nonce, challenges.values())
                    challenges[response["challenge_id"]] = nonce
                elif step["body"].get("credential_version") == 2:
                    nonce = challenges[step["body"]["challenge_id"]]
                    proof = hmac.new(
                        auth,
                        b"openmates/password-v2/proof\0login\0" + nonce,
                        hashlib.sha256,
                    ).digest()
                    self.assertEqual(
                        step["body"]["password_proof"],
                        base64.urlsafe_b64encode(proof).decode().rstrip("="),
                    )

    def test_matcher_refuses_added_fields_wrong_reference_and_reused_session(self):
        captures = {}
        session = "11111111-1111-4111-8111-111111111111"
        RUNNER.match(session, {"$capture_uuid": "first"}, captures)
        RUNNER.match(session, {"$ref": "first"}, captures)
        for actual, expected in [
            (session, {"$capture_uuid": "second"}),
            ("22222222-2222-4222-8222-222222222222", {"$ref": "first"}),
            ({"safe": True, "extra": True}, {"safe": True}),
            ({"safe": False}, {"safe": True}),
        ]:
            with self.assertRaises(AssertionError):
                RUNNER.match(actual, expected, deepcopy(captures))
        with self.assertRaises(ValueError):
            RUNNER.match("not-a-uuid", {"$capture_uuid": "second"}, {})

    def test_owner_assertion_fixture_keeps_principal_when_cookie_changes(self):
        vectors = GENERATOR.build()["capabilities"][RUNNER.CAPABILITY]["vectors"]
        vector = next(
            v
            for v in vectors
            if v["id"] == "owner-assertion-refuses-switched-cookie-before-logout"
        )
        protected = vector["steps"][-1]
        self.assertEqual(protected["expected_principal"], vector["account"]["owner_id"])
        self.assertNotEqual(
            protected["authenticated_principal"], protected["expected_principal"]
        )
        self.assertEqual(protected["cookie"], "auth_refresh_token=synthetic-owner-b")
        self.assertEqual(protected["response"]["status"], 403)
        self.assertEqual(
            vector["actions"][-2]["snapshot"]["token"], "synthetic-owner-b"
        )
        self.assertEqual(
            vector["actions"][-1],
            {"kind": "logout", "snapshot": None, "error": "forbidden"},
        )

    def test_closed_mismatch_vector_revokes_current_snapshot_instead_of_adopting_owner_b(
        self,
    ):
        vector = next(
            v
            for v in GENERATOR.build()["capabilities"][RUNNER.CAPABILITY]["vectors"]
            if v["id"] == "closed-owner-mismatch-revokes-current-credentials"
        )
        self.assertEqual(vector["steps"][-1]["path"], "/v1/auth/session")
        self.assertEqual(
            vector["steps"][-1]["expected_principal"], vector["account"]["owner_id"]
        )
        self.assertEqual(
            vector["actions"][-2],
            {"kind": "validate", "snapshot": None, "error": "expired"},
        )
        self.assertEqual(vector["actions"][-1], {"kind": "logout", "snapshot": None})


# contract-test-file: tooling


class PasswordPreferenceFixtureTests(unittest.TestCase):
    def test_omitted_false_true_and_tfa_fallback_keep_server_preference(self):
        vectors = GENERATOR.build()["capabilities"][RUNNER.CAPABILITY]["vectors"]
        for family in [
            "password-v2-serialized-cookie-rotation",
            "password-v2-totp-challenge-and-retry",
        ]:
            for suffix, preference in [
                ("", False),
                ("-stay-logged-in-false", False),
                ("-stay-logged-in-true", True),
            ]:
                vector = next(v for v in vectors if v["id"] == family + suffix)
                logins = [a for a in vector["actions"] if a["kind"] == "login"]
                self.assertTrue(logins)
                for action in logins:
                    if suffix:
                        self.assertIs(action["stay_logged_in"], preference)
                    else:
                        self.assertNotIn("stay_logged_in", action)
                requests = [s for s in vector["steps"] if s["path"] == "/v1/auth/login"]
                for step in requests:
                    self.assertIs(step["body"]["stay_logged_in"], preference)
                if "totp" in family:
                    self.assertTrue(
                        any(s["body"]["credential_version"] == 1 for s in requests)
                    )
                    self.assertTrue(
                        any(
                            s["body"].get("tfa_code") == vector["totp"]["code"]
                            for s in requests
                        )
                    )

    def test_v1_success_keeps_true_across_proof_fallback_and_otp_retry(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        fixture = GENERATOR.build()
        for vector in fixture["capabilities"][RUNNER.CAPABILITY]["vectors"]:
            if not vector["id"].endswith("-v1-success"):
                continue
            preference = "-true-" in vector["id"]
            requests = [s for s in vector["steps"] if s["path"] == "/v1/auth/login"]
            for step in requests:
                self.assertIs(step["body"]["stay_logged_in"], preference)
            success = requests[-1]
            self.assertEqual(success["body"]["credential_version"], 1)
            self.assertEqual(requests[-2]["body"]["credential_version"], 2)
            self.assertFalse(requests[-2]["response"]["json"]["success"])
            if "totp" in vector["id"]:
                self.assertEqual(success["body"]["tfa_code"], vector["totp"]["code"])
                self.assertEqual(
                    len([a for a in vector["actions"] if a["kind"] == "login"]), 2
                )
            user = success["response"]["json"]["user"]
            key = hashlib.pbkdf2_hmac(
                "sha256",
                vector["account"]["password"].encode(),
                base64.b64decode(user["salt"]),
                100000,
            )
            opened = AESGCM(key).decrypt(
                base64.b64decode(user["key_iv"]),
                base64.b64decode(user["encrypted_key"]),
                None,
            )
            self.assertEqual(opened, base64.b64decode(vector["account"]["master_key"]))


if __name__ == "__main__":
    unittest.main()
