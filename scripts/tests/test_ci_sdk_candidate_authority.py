# contract-test-file: tooling
"""Inert canonical-metadata/Git doubles plus actual maintained file checks.

No compiler, adapter, SDK product, account, process lifecycle or CI is launched.
The Git double models immutable blobs; full publication integration stays open.
"""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SOURCE = "7c867871255bb95c960f263bb2e96b3db7b6cf59"
TREE = "6e76a11cff36298235a7a8cd268c223864d92703"
AUTH = "172aaf41267b607f13b42c8e475adc9b3d96ee6f43322ec987492673b22371ce"
CURRENT = "b" * 40
ORIGINAL = "c" * 40


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class CandidateAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory(prefix="candidate-authority-")
        self.addCleanup(self.owner.cleanup)
        self.base = Path(self.owner.name)
        self.canonical = self.base / "tooling"
        self.subject = self.base / "subject"
        (self.canonical / "scripts").mkdir(parents=True)
        (self.subject / "scripts").mkdir(parents=True)
        self.m = module(
            "candidate_authority_unit", SCRIPTS / "ci_sdk_candidate_authority.py"
        )
        self.sdk = module(
            "candidate_authority_sdk_unit", SCRIPTS / "ci_sdk_conformance.py"
        )
        helper = self.canonical / "scripts/ci_sdk_candidate_authority.py"
        helper.write_bytes((SCRIPTS / "ci_sdk_candidate_authority.py").read_bytes())
        self.m.__file__ = str(helper)
        self.manifest_name = self.m.MANIFESTS + "/" + AUTH + ".json"
        self.manifest = (
            SCRIPTS / self.manifest_name.removeprefix("scripts/")
        ).read_bytes()
        self.assertEqual(hashlib.sha256(self.manifest).hexdigest(), AUTH)
        self.registry = json.loads(
            (SCRIPTS / "ci_sdk_candidate_authorities.json").read_bytes()
        )
        self.committed = {}
        self.commit_registry(self.registry)
        self.commit_file(CURRENT, self.manifest_name, self.manifest)
        (self.subject / self.m.CANDIDATE_MANIFEST).write_bytes(self.manifest)
        self.committed[(SOURCE, self.m.CANDIDATE_MANIFEST)] = (b"100644", self.manifest)
        self.default = {
            "programs": {"probe.rs": hashlib.sha256(b"old").hexdigest()},
            "contracts": {},
        }
        self.commit_file(
            CURRENT, self.m.CANDIDATE_MANIFEST, json.dumps(self.default).encode()
        )
        self.commit_file(
            ORIGINAL, self.m.CANDIDATE_MANIFEST, json.dumps(self.default).encode()
        )
        self.default_calls = 0
        self.head = SOURCE
        self.git_calls = []
        self.addCleanup(patch.stopall)
        patch.object(self.m, "_git", side_effect=self.git).start()

    def commit_file(self, revision, name, raw):
        if revision == CURRENT:
            target = self.canonical / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.committed[(revision, name)] = (b"100644", raw)

    def commit_registry(self, value, revision=CURRENT):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.commit_file(revision, self.m.REGISTRY, raw)

    def git(self, root, *args):
        self.git_calls.append((root, args))
        if args == ("rev-parse", "--show-toplevel"):
            return str(self.canonical).encode() + b"\n"
        if args == ("rev-parse", "HEAD"):
            return (CURRENT if root == self.canonical else self.head).encode() + b"\n"
        if args[0] == "rev-parse" and args[1].endswith("^{commit}"):
            ref = args[1][:-9]
            if ref not in (CURRENT, ORIGINAL, SOURCE):
                raise subprocess.CalledProcessError(1, "git fixture")
            return ref.encode() + b"\n"
        if args == ("rev-parse", SOURCE + "^{tree}"):
            return TREE.encode() + b"\n"
        if args[:2] == ("ls-tree", "-z"):
            entry = self.committed.get((args[2], args[4]))
            if entry is None:
                return b""
            mode, raw = entry
            oid = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            return mode + b" blob " + oid.encode() + b"\t" + args[4].encode() + b"\0"
        if args[0] == "cat-file":
            for _, raw in self.committed.values():
                oid = hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest()
                if oid == args[2]:
                    return str(len(raw)).encode() + b"\n" if args[1] == "-s" else raw
        raise AssertionError((root, args))

    def default_loader(self):
        self.default_calls += 1
        return copy.deepcopy(self.default)

    def select(self, source=SOURCE, **kwargs):
        return self.m.select_trust(
            self.subject,
            source,
            load_default=self.default_loader,
            regular=self.sdk.regular,
            require=self.sdk.require,
            **kwargs,
        )

    def test_exact_registered_source_selects_only_reviewed_full_manifest(self):
        result = self.select(checkout=True)
        self.assertEqual(result, json.loads(self.manifest))
        self.assertEqual(len(result["programs"]) + len(result["contracts"]), 1142)
        self.assertEqual(self.default_calls, 0)

    def test_unregistered_source_keeps_original_default_verification(self):
        result = self.select("a" * 40)
        self.assertEqual(result, self.default)
        self.assertEqual(self.default_calls, 1)
        (self.subject / "probe.rs").write_bytes(b"changed")
        with self.assertRaisesRegex(self.sdk.Refused, "reviewed_program_changed"):
            self.sdk.verify_programs(self.subject, result)

    def test_environment_or_prefix_never_selects_candidate_authority(self):
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": "/untrusted",
                "SDK_TRUST_PATH": "/untrusted",
                "SDK_AUTHORITY_SHA256": AUTH,
                "BUILD_COMMIT_SHA": SOURCE,
            },
        ):
            self.assertEqual(self.select("a" + SOURCE[1:]), self.default)
        for source in (SOURCE[:12], SOURCE.upper(), "../" + SOURCE, None):
            with self.subTest(source=source), self.assertRaises(self.sdk.Refused):
                self.select(source)

    def test_cross_source_tree_refuses_without_default_fallback(self):
        wrong = copy.deepcopy(self.registry)
        wrong["registrations"][0]["sourceTree"] = "0" * 40
        self.commit_registry(wrong)
        with self.assertRaisesRegex(
            self.sdk.Refused, "candidate_authority_source_tree"
        ):
            self.select()
        self.assertEqual(self.default_calls, 0)

    def test_well_formed_wrong_authority_digest_is_not_a_fallback(self):
        wrong = copy.deepcopy(self.registry)
        wrong["registrations"][0]["authoritySha256"] = "0" * 64
        self.commit_registry(wrong)
        self.commit_file(
            CURRENT, self.m.MANIFESTS + "/" + "0" * 64 + ".json", self.manifest
        )
        with self.assertRaisesRegex(
            self.sdk.Refused, "candidate_authority_manifest_changed"
        ):
            self.select()
        self.assertEqual(self.default_calls, 0)

    def test_duplicate_conflicting_or_malformed_registry_refuses(self):
        values = []
        for change in (self.registry["registrations"] * 2, {}, None):
            value = copy.deepcopy(self.registry)
            value["registrations"] = change
            values.append(value)
        for key, value in (("schemaVersion", True), ("extra", "untrusted")):
            changed = copy.deepcopy(self.registry)
            changed[key] = value
            values.append(changed)
        invalid = copy.deepcopy(self.registry)
        invalid["registrations"][0]["authoritySha256"] = "../manifest"
        values.extend(
            [invalid, b'{"schemaVersion":1,"schemaVersion":1,"registrations":[]}']
        )
        for value in values:
            with self.subTest(value=value):
                self.commit_registry(value)
                with self.assertRaises(self.sdk.Refused):
                    self.select()
        self.assertEqual(self.default_calls, 0)

    def test_tampered_registry_and_manifest_refuse(self):
        for name in (self.m.REGISTRY, self.manifest_name):
            target = self.canonical / name
            raw = target.read_bytes()
            target.write_bytes(raw + b"\n")
            with self.subTest(name=name), self.assertRaises(self.sdk.Refused):
                self.select()
            target.write_bytes(raw)
        self.assertEqual(self.default_calls, 0)

    def test_missing_symlink_world_writable_and_oversized_manifest_refuse(self):
        target = self.canonical / self.manifest_name
        target.unlink()
        with self.assertRaises(OSError):
            self.select()
        other = self.base / "outside.json"
        other.write_bytes(self.manifest)
        target.symlink_to(other)
        with self.assertRaises(self.sdk.Refused):
            self.select()
        target.unlink()
        target.write_bytes(self.manifest)
        target.chmod(0o666)
        with self.assertRaises(self.sdk.Refused):
            self.select()
        target.chmod(0o600)
        target.write_bytes(b"x" * (self.m.MANIFEST_LIMIT + 1))
        with self.assertRaises(self.sdk.Refused):
            self.select()
        self.assertEqual(self.default_calls, 0)

    def test_oversized_registry_or_committed_manifest_refuses(self):
        target = self.canonical / self.m.REGISTRY
        target.write_bytes(b"x" * (self.m.REGISTRY_LIMIT + 1))
        with self.assertRaises(self.sdk.Refused):
            self.select()
        self.commit_registry(self.registry)
        raw = b"x" * (self.m.MANIFEST_LIMIT + 1)
        self.commit_file(CURRENT, self.manifest_name, raw)
        with self.assertRaises(self.sdk.Refused):
            self.select()

    def test_git_symlink_or_missing_manifest_refuses(self):
        key = (CURRENT, self.manifest_name)
        for entry in ((b"120000", self.manifest), None):
            if entry is None:
                self.committed.pop(key, None)
            else:
                self.committed[key] = entry
            with self.subTest(entry=entry is None), self.assertRaises(self.sdk.Refused):
                self.select()

    def test_candidate_git_or_checkout_manifest_and_head_must_stay_exact(self):
        key = (SOURCE, self.m.CANDIDATE_MANIFEST)
        self.committed[key] = (b"100644", self.manifest + b"\n")
        with self.assertRaisesRegex(
            self.sdk.Refused, "candidate_authority_source_manifest"
        ):
            self.select()
        self.committed[key] = (b"100644", self.manifest)
        target = self.subject / self.m.CANDIDATE_MANIFEST
        target.write_bytes(self.manifest + b"\n")
        with self.assertRaisesRegex(
            self.sdk.Refused, "candidate_authority_checkout_changed"
        ):
            self.select(checkout=True)
        target.write_bytes(self.manifest)
        self.head = "a" * 40
        with self.assertRaisesRegex(self.sdk.Refused, "source_identity"):
            self.select(checkout=True)
        self.assertEqual(self.default_calls, 0)

    def test_retrieval_current_b_original_a_source_a_selects_a(self):
        self.commit_registry(self.registry, revision=ORIGINAL)
        self.commit_file(ORIGINAL, self.manifest_name, self.manifest)
        later = copy.deepcopy(self.registry)
        later["registrations"][0]["sourceCommit"] = "a" * 40
        self.commit_registry(later)
        # A's old manifest need not survive in today's checkout or ledger.
        self.committed.pop((CURRENT, self.manifest_name))
        (self.canonical / self.manifest_name).unlink()
        self.assertEqual(self.select(harness=ORIGINAL), json.loads(self.manifest))
        self.assertEqual(self.default_calls, 0)
        registry_reads = [
            args[2]
            for root, args in self.git_calls
            if root == self.canonical
            and args[:2] == ("ls-tree", "-z")
            and args[4] == self.m.REGISTRY
        ]
        self.assertEqual(registry_reads, [ORIGINAL])

    def test_original_unregistered_source_keeps_original_public_default(self):
        old = copy.deepcopy(self.registry)
        old["registrations"][0]["sourceCommit"] = "a" * 40
        self.commit_registry(old, revision=ORIGINAL)
        # Current registers SOURCE; the original public interpretation still wins.
        self.assertEqual(self.select(harness=ORIGINAL), self.default)
        self.assertEqual(self.default_calls, 0)
        self.assertEqual(self.select(harness=CURRENT), json.loads(self.manifest))

    def test_old_public_job_can_predate_registry_even_if_source_registered_later(self):
        self.assertNotIn((ORIGINAL, self.m.REGISTRY), self.committed)
        for source in ("a" * 40, SOURCE):
            with self.subTest(source=source):
                self.assertEqual(self.select(source, harness=ORIGINAL), self.default)
        self.assertEqual(self.default_calls, 0)

    def test_original_public_default_survives_current_default_evolution(self):
        original = copy.deepcopy(self.default)
        self.default["programs"]["probe.rs"] = hashlib.sha256(b"new").hexdigest()
        self.commit_file(
            CURRENT, self.m.CANDIDATE_MANIFEST, json.dumps(self.default).encode()
        )
        for registrations in (
            None,
            [],
            [
                {
                    "sourceCommit": "a" * 40,
                    "sourceTree": "0" * 40,
                    "authoritySha256": "0" * 64,
                }
            ],
        ):
            with self.subTest(registrations=registrations):
                if registrations is not None:
                    self.commit_registry(
                        {"schemaVersion": 1, "registrations": registrations},
                        revision=ORIGINAL,
                    )
                result = self.select(harness=ORIGINAL)
                self.assertEqual(result, original)
                self.assertNotEqual(result, self.default)
                (self.subject / "probe.rs").write_bytes(b"new")
                with self.assertRaisesRegex(
                    self.sdk.Refused, "reviewed_program_changed"
                ):
                    self.sdk.verify_programs(self.subject, result)
        self.assertEqual(self.default_calls, 0)
        self.assertEqual(self.select("a" * 40), self.default)
        self.assertEqual(self.default_calls, 1)

    def test_original_matched_bad_authority_refuses_without_public_fallback(self):
        self.commit_registry(self.registry, revision=ORIGINAL)
        with self.assertRaisesRegex(self.sdk.Refused, "candidate_authority_git_file"):
            self.select(harness=ORIGINAL)
        self.commit_file(ORIGINAL, self.manifest_name, self.manifest + b"\n")
        with self.assertRaisesRegex(
            self.sdk.Refused, "candidate_authority_manifest_changed"
        ):
            self.select(harness=ORIGINAL)
        for change in ("malformed", "conflicting"):
            wrong = copy.deepcopy(self.registry)
            if change == "malformed":
                wrong["registrations"][0]["authoritySha256"] = "../manifest"
            else:
                wrong["registrations"].append(copy.deepcopy(wrong["registrations"][0]))
                wrong["registrations"][1]["authoritySha256"] = "0" * 64
            self.commit_registry(wrong, revision=ORIGINAL)
            with self.subTest(change=change), self.assertRaises(self.sdk.Refused):
                self.select(harness=ORIGINAL)
        self.assertEqual(self.default_calls, 0)

    def test_multiple_exact_entries_select_by_source_and_empty_registry_defaults(self):
        expanded = copy.deepcopy(self.registry)
        expanded["registrations"].insert(
            0,
            {
                "sourceCommit": "a" * 40,
                "sourceTree": "0" * 40,
                "authoritySha256": "0" * 64,
            },
        )
        self.commit_registry(expanded)
        self.assertEqual(self.select(), json.loads(self.manifest))
        self.commit_registry({"schemaVersion": 1, "registrations": []})
        self.assertEqual(self.select(), self.default)
        self.assertEqual(self.default_calls, 1)

    def test_no_argument_public_loader_is_unchanged(self):
        raw = json.dumps(self.default).encode()
        with patch.object(self.sdk, "regular", return_value=raw) as read:
            self.assertEqual(self.sdk.load_trust(), self.default)
        read.assert_called_once_with(
            Path(self.sdk.__file__).with_name("ci_sdk_conformance_trust.json"),
            2 * 1024**2,
        )

    def test_git_subprocess_cannot_inherit_candidate_routing(self):
        # Exercise the actual helper's subprocess boundary in a separate module;
        # the subprocess itself is inert and no Git/repository is created.
        fresh = module(
            "candidate_authority_git_boundary",
            SCRIPTS / "ci_sdk_candidate_authority.py",
        )
        with patch.dict(os.environ, {"GIT_DIR": "/untrusted", "GIT_CONFIG_COUNT": "9"}):
            with patch.object(fresh.subprocess, "run") as run:
                run.return_value.stdout = b"actual-output"
                self.assertEqual(
                    fresh._git(self.subject, "rev-parse", "HEAD"), b"actual-output"
                )
                command = run.call_args.args[0]
                options = run.call_args.kwargs
                self.assertEqual(
                    command[:4],
                    ["/usr/bin/git", "--no-replace-objects", "-C", str(self.subject)],
                )
                self.assertNotIn("GIT_DIR", options["env"])
                self.assertNotIn("GIT_CONFIG_COUNT", options["env"])
                self.assertEqual(options["timeout"], 15)


if __name__ == "__main__":
    unittest.main()
