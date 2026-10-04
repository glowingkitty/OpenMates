# contract-test-file: tooling
"""Mocked Cargo cache/runtime packaging checks; no native compilation or models."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


BRIDGE = Path(__file__).resolve().parent
PANIC = "__RNvNtCs82bWklYMk3w_3std9panicking11EMPTY_PANIC"
INTEL_PANIC = "__RNvNtCsIntel123456_3std9panicking11EMPTY_PANIC"
ABI = {"_om_pocket_create", "_om_pocket_synthesize", "_om_pocket_audio_bytes",
       "_om_pocket_audio_count", "_om_pocket_audio_free", "_om_pocket_destroy"}


class PocketBuildPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pocket-package-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bridge = self.root / "apple/PocketTTSBridge"
        self.bridge.mkdir(parents=True)
        for name in ["build-apple.sh", "local-runtime-symbols.txt"]:
            shutil.copyfile(BRIDGE / name, self.bridge / name)
        (self.bridge / "prepare.py").write_text("# Synthetic source preparation: no downloads.\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ["cargo", "rustup"]:
            path = self.bin / tool
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        xcrun = self.bin / "xcrun"
        xcrun.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
log = pathlib.Path(os.environ["MOCK_TOOL_LOG"])
with log.open("a") as stream: stream.write(json.dumps(args) + "\\n")
mode = os.environ.get("MOCK_FAILURE", "")
failure_arch = os.environ.get("MOCK_FAILURE_ARCH", "")
if args[0] == "lipo":
    if mode == "lipo": sys.exit(19)
    if args[1] == "-create":
        slices = {}
        for name in args[2:args.index("-output")]:
            item = json.loads(pathlib.Path(name).read_text())
            slices[item["architecture"]] = item
        if mode == "corrupt-lipo":
            slices[failure_arch or "x86_64"]["exports"].remove("_om_pocket_create")
        state = {"slices": slices}
    elif args[1] == "-thin":
        state = json.loads(pathlib.Path(args[3]).read_text())["slices"][args[2]]
    else: sys.exit("Unexpected lipo invocation")
    pathlib.Path(args[-1]).write_text(json.dumps(state))
    sys.exit(0)
archive = pathlib.Path(args[-1])
state = json.loads(archive.read_text())
affects_slice = not failure_arch or failure_arch == state["architecture"]
if mode == args[0] and affects_slice: sys.exit(19)
if args[0] == "nm":
    assert "--no-llvm-bc" in args and "--quiet" in args
    print("\\n".join(state["undefined" if "-gu" in args else "exports"]))
elif args[0] == "nmedit":
    assert args[1] == "-R"
    names = set(pathlib.Path(args[2]).read_text().splitlines())
    # Apple's nmedit rejects names absent from a selected architecture.
    if not names <= set(state["exports"]): sys.exit("Removal list contains undefined symbols")
    state["exports"] = [name for name in state["exports"] if name not in names]
    if mode == "remove-abi" and affects_slice: state["exports"].remove("_om_pocket_create")
    archive.write_text(json.dumps(state))
else: sys.exit("Unexpected native tool invocation")
''')
        xcrun.chmod(0o755)
        self.log = self.root / "tool-calls.jsonl"
        self.derived = self.root / "derived"
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "DERIVED_FILE_DIR": str(self.derived), "PLATFORM_NAME": "macosx", "ARCHS": "arm64",
                    "MOCK_TOOL_LOG": str(self.log)}

    def seed(self, exports=None, undefined=None, target="aarch64-apple-darwin"):
        source = self.root / f".runtime/pocket-tts/target/{target}/release/libopenmates_pocket_tts.a"
        source.parent.mkdir(parents=True, exist_ok=True)
        architecture = "x86_64" if target.startswith("x86_64") else "arm64"
        source.write_text(json.dumps({"architecture": architecture, "exports": sorted(exports if exports is not None else
            ABI | {PANIC, "_rust_eh_personality", "_unrelated_cpp_export"}), "undefined": undefined or []}))
        return source

    def run_build(self, **overrides):
        return subprocess.run(["bash", str(self.bridge / "build-apple.sh")],
            env={**self.env, **overrides}, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def output(self):
        return self.derived / "PocketTTS/libopenmates_pocket_tts.a"

    def test_cached_unlocalized_archive_is_repackaged_each_build_preserving_abi(self):
        source = self.seed()
        original = source.read_bytes()
        self.output().parent.mkdir(parents=True)
        self.output().write_text("stale unvalidated DerivedSources output")
        for _ in range(2):
            result = self.run_build()
            self.assertEqual(result.returncode, 0, result.stderr)
            exports = set(json.loads(self.output().read_text())["exports"])
            self.assertEqual(exports, ABI | {"_unrelated_cpp_export"})
            self.assertEqual(source.read_bytes(), original, "Cargo's cached archive must remain immutable")
        self.assertEqual(sum(call[0] == "nmedit" for call in self.calls()), 2)
        # Xcode also reruns this script, rather than trusting an old output.
        project = BRIDGE.parent.joinpath("project.yml").read_text()
        block = project.split("- name: Build PocketTTSBridge", 1)[1].split("- name:", 1)[0]
        self.assertIn("basedOnDependencyAnalysis: false", block)

    def test_runtime_identity_is_discovered_without_hiding_unrelated_symbols(self):
        other_slice = "__RNvNtCs123456789_3std9panicking11EMPTY_PANIC"
        unrelated = "_my_crate_EMPTY_PANIC"
        self.seed(exports=ABI | {PANIC, other_slice, unrelated, "_rust_eh_personality"})
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(self.output().read_text())["exports"]), ABI | {unrelated})

    def test_cross_object_undefined_reference_rejects_before_mutation(self):
        source = self.seed(undefined=[PANIC])
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cross-object references", result.stderr)
        self.assertFalse(any(call[0] == "nmedit" for call in self.calls()))
        self.assertFalse(self.output().exists(), "An unverified archive must not be published")
        self.assertIn(PANIC, json.loads(source.read_text())["exports"])

    def test_missing_runtime_or_abi_rejects_before_mutation(self):
        for exports in [ABI | {"_rust_eh_personality"}, (ABI - {"_om_pocket_create"}) | {PANIC}]:
            with self.subTest(exports=exports):
                self.seed(exports=exports)
                result = self.run_build()
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == "nmedit" for call in self.calls()))

    def test_symbol_inspection_and_edit_failures_stop_packaging(self):
        self.seed()
        for mode in ["nm", "nmedit", "remove-abi"]:
            with self.subTest(mode=mode):
                result = self.run_build(MOCK_FAILURE=mode)
                self.assertNotEqual(result.returncode, 0)
                if mode == "remove-abi": self.assertIn("changed unexpected exported symbols", result.stderr)

    def test_universal_architectures_localize_distinct_rust_identities_on_every_build(self):
        arm = self.seed(exports=ABI | {PANIC, "_rust_eh_personality", "_arm_only_export"})
        intel = self.seed(target="x86_64-apple-darwin",
            exports=ABI | {INTEL_PANIC, "_rust_eh_personality", "_intel_only_export"})
        originals = {path: path.read_bytes() for path in [arm, intel]}
        for _ in range(2):
            result = self.run_build(ARCHS="arm64 x86_64")
            self.assertEqual(result.returncode, 0, result.stderr)
            slices = json.loads(self.output().read_text())["slices"]
            self.assertEqual(set(slices), {"arm64", "x86_64"})
            for arch, unrelated in [("arm64", "_arm_only_export"), ("x86_64", "_intel_only_export")]:
                self.assertEqual(set(slices[arch]["exports"]), ABI | {unrelated})
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original, "Packaging must preserve each cached Cargo archive")
        calls = self.calls()
        self.assertEqual(sum(call[0] == "nmedit" for call in calls), 4)
        self.assertEqual(sum(call[:2] == ["lipo", "-thin"] for call in calls), 4)
        self.assertEqual(list(self.output().parent.glob(".runtime-slices-*")), [])

    def test_universal_second_slice_preflight_failure_prevents_all_localization(self):
        arm = self.seed()
        intel = self.seed(target="x86_64-apple-darwin", undefined=[INTEL_PANIC],
            exports=ABI | {INTEL_PANIC, "_rust_eh_personality"})
        originals = {path: path.read_bytes() for path in [arm, intel]}
        self.output().parent.mkdir(parents=True)
        self.output().write_text("previous completed packaging")
        result = self.run_build(ARCHS="arm64 x86_64")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cross-object references in x86_64", result.stderr)
        self.assertFalse(any(call[0] == "nmedit" for call in self.calls()))
        self.assertEqual(self.output().read_text(), "previous completed packaging")
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_universal_partial_edit_and_combination_failures_never_publish(self):
        arm = self.seed()
        intel = self.seed(target="x86_64-apple-darwin",
            exports=ABI | {INTEL_PANIC, "_rust_eh_personality", "_intel_only_export"})
        originals = {path: path.read_bytes() for path in [arm, intel]}
        self.output().parent.mkdir(parents=True)
        for mode in ["nmedit", "remove-abi", "lipo", "corrupt-lipo"]:
            with self.subTest(mode=mode):
                self.output().write_text("previous completed packaging")
                result = self.run_build(ARCHS="arm64 x86_64", MOCK_FAILURE=mode, MOCK_FAILURE_ARCH="x86_64")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.output().read_text(), "previous completed packaging")
                if mode == "remove-abi":
                    self.assertIn("x86_64 runtime localization changed unexpected exported symbols", result.stderr)
                if mode == "corrupt-lipo":
                    self.assertIn("x86_64 combined archive changed unexpected exported symbols", result.stderr)
                for path, original in originals.items():
                    self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(self.output().parent.glob(".runtime-slices-*")), [])

    def test_ios_keeps_the_existing_personality_only_policy(self):
        self.seed(target="aarch64-apple-ios-sim")
        result = self.run_build(PLATFORM_NAME="iphonesimulator")
        self.assertEqual(result.returncode, 0, result.stderr)
        exports = set(json.loads(self.output().read_text())["exports"])
        self.assertEqual(exports, ABI | {PANIC, "_unrelated_cpp_export"})
        self.assertEqual([call[0] for call in self.calls()], ["nmedit"])

    def test_mac_app_retains_dwarf_unwind_for_both_architectures_only(self):
        project = BRIDGE.parent.joinpath("project.yml").read_text()
        app = re.split(r"\n  (?=\S)", project.split("\n  OpenMates:", 1)[1], maxsplit=1)[0]
        conditional_flags = dict(re.findall(r'^\s+"(OTHER_LDFLAGS\[[^"]+)": \'([^\']+)\'$', app, re.MULTILINE))
        expected = {"OTHER_LDFLAGS[sdk=macosx*][arch=arm64]",
                    "OTHER_LDFLAGS[sdk=macosx*][arch=x86_64]"}
        self.assertEqual({key for key, value in conditional_flags.items() if "-no_compact_unwind" in value}, expected)
        self.assertEqual({key for key, value in conditional_flags.items() if "-keep_dwarf_unwind" in value}, expected)
        for key in expected:
            self.assertTrue(conditional_flags[key].startswith("$(inherited) "))
            self.assertIn("-Xlinker -no_compact_unwind -Xlinker -keep_dwarf_unwind", conditional_flags[key])
        arm_flags = conditional_flags["OTHER_LDFLAGS[sdk=macosx*][arch=arm64]"]
        self.assertEqual(arm_flags.count("-force_load"), 6)
        for name in ["executorch", "backend_xnnpack", "kernels_optimized", "kernels_quantized", "kernels_torchao", "threadpool"]:
            self.assertIn(f"/macosx/{name}.xcframework/", arm_flags)
        self.assertIn('-lopenmates_pair_opaque -lopenmates_pocket_tts -lc++', app)
        self.assertNotIn("-no_dwarf_unwind", project)


if __name__ == "__main__":
    unittest.main()
