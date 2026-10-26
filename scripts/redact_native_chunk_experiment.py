#!/usr/bin/env python3
"""Private, resource-bounded Redact rebuild. Never runs model inference."""
from __future__ import annotations

import argparse
import difflib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import struct
import subprocess
import tarfile
import time
import urllib.request

import redact_brotli_guard

SDK_COMMIT = "86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb"
SWIFT_NAME = "swift-6.3.3-RELEASE-ubuntu24.04-aarch64"
SWIFT_URL = f"https://download.swift.org/swift-6.3.3-release/ubuntu2404-aarch64/swift-6.3.3-RELEASE/{SWIFT_NAME}.tar.gz"
SOURCE_URL = f"https://codeload.github.com/Desert-Ant-Labs/desert-ant-core/tar.gz/{SDK_COMMIT}"
MIN_FREE = 30 * 1024**3
MAX_DISK = 5_000_000_000
MARGIN = 128 * 1024**2
MIN_MEMORY = 2 * 1024**3
MEMORY_ADMISSION = 4 * 1024**3
SWIFT_SHA256 = "47126395429653fa768d370655876ec1b68f6a95c7884f5e4f179700141c9b7f"
SOURCE_SHA256 = "6143aaeea8dfa8801df0bf5e8a111eddb430515f6f3350460df27bc1b55a7c2e"
EXPECTED_LITERT = "fb21752e51cb9def7e154ccc65c7a12460d2c3c3116a50b4bb42e24dbc96128c"
EXPECTED_MODEL_SOURCE = "eb600035eb92e728ddc14b258dcc808c0cf331a3c15b2c3f1701b097784e15bf"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def owned_bytes(root: Path) -> int:
    total = 0
    seen = set()
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                info = (Path(directory) / name).lstat()
            except FileNotFoundError:
                continue
            identity = (info.st_dev, info.st_ino)
            if identity not in seen:
                seen.add(identity)
                total += info.st_blocks * 512
    return total


def available_memory() -> int:
    return next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))


class Experiment:
    def __init__(self, root: Path, brotli_prefix: Path, parallel: bool = False, fast_gaps: bool = False):
        self.root = root
        self.parallel = parallel
        self.fast_gaps = fast_gaps
        self.build_root = root.parent / "parallel-experiment" if fast_gaps else root
        self.resource_root = root.parent if parallel else root
        self.receipt_path = root / "receipt.json"
        self.receipt = json.loads(self.receipt_path.read_text()) if self.receipt_path.exists() else {}
        self.build_env = redact_brotli_guard.child_environment(brotli_prefix, dict(os.environ))
        self.receipt.update({"sdk_commit": SDK_COMMIT, "swift": "6.3.3", "cpus": [12, 13, 14, 15], "nice": 10, "max_disk_bytes": MAX_DISK, "min_free_bytes": MIN_FREE, "min_memory_available_bytes": MIN_MEMORY, "memory_archive_admission_bytes": MEMORY_ADMISSION, "brotli_prefix": str(brotli_prefix), "inference_executed": False})
        self.receipt["benchmark_environment"] = {
            "DAL_REDACT_BENCH_MAX_CHARS": {"minimum": 150, "maximum": 600, "default": 150},
            "DAL_REDACT_BENCH_CARRY": {"minimum": 0, "maximum": 1, "default": 1},
            "compile_guard": "os(Linux) && DAL_REDACT_BENCHMARK_CHUNKING",
            "missing_overrides_preserve_defaults": True,
        }
        if parallel:
            self.receipt["benchmark_environment"].update({
                "DAL_REDACT_BENCH_WORKERS": {"minimum": 1, "maximum": 8, "default": 1},
                "parallel_compile_guard": "os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL",
                "independent_compiled_sessions": True,
                "sessions_initialized_during_model_load": True,
                "chunk_order_preserved": True,
                "global_postprocessing_passes": 1,
            })
            self.receipt["resource_accounting_root"] = str(self.resource_root)
        if fast_gaps:
            self.receipt["parallel_fast_gaps"] = True
            self.receipt["benchmark_environment"].update({
                "DAL_REDACT_BENCH_FAST_GAPS": {"minimum": 0, "maximum": 1, "default": 0},
                "fast_gaps_compile_guard": "os(Linux) && DAL_REDACT_BENCHMARK_FAST_GAPS",
            })

    def record(self, phase: str, **fields):
        if phase != "stopped" and "error" in self.receipt:
            self.receipt.setdefault("previous_attempt_errors", []).append(self.receipt.pop("error"))
        self.receipt.update(fields)
        self.receipt["phase"] = phase
        self.receipt["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        temporary = self.root / "receipt.json.tmp"
        temporary.write_text(json.dumps(self.receipt, indent=2) + "\n")
        temporary.replace(self.receipt_path)
        print(json.dumps({"phase": phase, **fields}), flush=True)

    def guard(self, additional: int = 0):
        free = shutil.disk_usage(self.root).free
        used = owned_bytes(self.resource_root)
        if free - additional < MIN_FREE + MARGIN or used + additional > MAX_DISK - MARGIN:
            raise RuntimeError(f"resource_admission: free={free}, task_bytes={used}, additional={additional}")
        if available_memory() < MIN_MEMORY + MARGIN:
            raise RuntimeError("memory_available_floor")

    def request(self, url: str, **kwargs):
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "OpenMates-Redact-Native-Benchmark/1.0", **kwargs.pop("headers", {})}, **kwargs), timeout=60)

    def download(self, url: str, destination: Path, limit: int):
        if destination.exists():
            return
        part = destination.with_suffix(destination.suffix + ".part")
        if part.exists():
            raise RuntimeError(f"incomplete_download_requires_review: {part.name}")
        count = 0
        try:
            with self.request(url) as response, part.open("xb") as handle:
                while chunk := response.read(4 * 1024**2):
                    count += len(chunk)
                    if count > limit:
                        raise RuntimeError("download_size_limit")
                    self.guard(len(chunk))
                    handle.write(chunk)
            part.replace(destination)
        except BaseException:
            # Only this operation's incomplete download is disposable.
            part.unlink(missing_ok=True)
            raise

    def run(self, name: str, command: list[str], *, cwd: Path | None = None, env=None, timeout=1200):
        log = self.root / f"{name}.log"
        started = time.monotonic()
        reported = started
        with log.open("ab") as output:
            child = subprocess.Popen(command, cwd=cwd, env=env or self.build_env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while child.poll() is None:
                    self.guard()
                    if time.monotonic() - started > timeout:
                        raise RuntimeError(f"{name}_timeout")
                    if time.monotonic() - reported >= 30:
                        reported = time.monotonic()
                        lines = log.read_text(errors="replace").splitlines()
                        print(json.dumps({"phase": name, "elapsed_seconds": round(reported - started), "last_build_step": lines[-1][-200:] if lines else "", "free_bytes": shutil.disk_usage(self.root).free}), flush=True)
                    time.sleep(1)
            except BaseException:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                raise
        if child.returncode:
            raise RuntimeError(f"{name}_failed: exit={child.returncode}; inspect {log.name}")
        return log.read_text(errors="replace")

    def extract(self, archive, destination: Path, *, expected_prefix: str | None = None):
        if destination.exists():
            if (destination / ".extraction-complete").exists():
                return
            raise RuntimeError(f"incomplete_extraction_requires_review: {destination.name}")
        archive_name = archive.name if isinstance(archive, Path) else "sealed-memory-toolchain"
        self.record("inspect-archive", archive=archive_name)
        arguments = {"name": archive} if isinstance(archive, Path) else {"fileobj": archive}
        with tarfile.open(mode="r:gz", **arguments) as package:
            members = package.getmembers()
            unpacked = sum(member.size for member in members if member.isfile())
            if not members or unpacked > MAX_DISK:
                raise RuntimeError("archive_member_size_limit")
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise RuntimeError("unsafe_archive_path")
                if expected_prefix and path.parts[0] != expected_prefix:
                    raise RuntimeError("archive_prefix_mismatch")
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise RuntimeError("unsupported_archive_member")
            self.guard(unpacked + len(members) * 4096)
            self.record("extract-archive", archive=archive_name, archive_member_bytes=unpacked, archive_members=len(members))
            destination.mkdir(mode=0o700)
            try:
                for index, member in enumerate(members):
                    if index % 64 == 0:
                        self.guard()
                    package.extract(member, destination, filter="data")
                (destination / ".extraction-complete").write_text("verified archive extraction completed\n")
            except BaseException:
                # An incomplete extraction has never been executable/proof output.
                shutil.rmtree(destination)
                raise

    def extract_toolchain_in_memory(self, archive: Path, destination: Path):
        memory_before = available_memory()
        if memory_before < MEMORY_ADMISSION:
            raise RuntimeError("memory_archive_admission")
        descriptor = os.memfd_create("openmates-swift-archive-678f", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            hasher = hashlib.sha256()
            copied = 0
            with archive.open("rb") as source:
                while chunk := source.read(64 * 1024):
                    # Copying to sealed memory cannot grow filesystem usage.
                    # Bound admission intervals to 8 MiB instead of rescanning
                    # the entire retained experiment tree for every 64 KiB.
                    if copied % (8 * 1024**2) == 0:
                        self.guard()
                    hasher.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    copied += len(chunk)
            if hasher.hexdigest() != SWIFT_SHA256 or copied != archive.stat().st_size:
                raise RuntimeError("memory_archive_hash_mismatch")
            seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL
            fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
            if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
                raise RuntimeError("memory_archive_not_immutable")
            self.record("toolchain-memory-archive-verified", memory_archive_bytes=copied, memory_available_before=memory_before, memory_available_after=available_memory(), memory_archive_sha256=hasher.hexdigest(), memory_archive_seals=seals, memory_archive_chunk_bytes=64 * 1024)
            # Explicitly authorized relocation: only the signature-verified disk
            # archive is removed, after the sealed RAM copy matches its hash.
            archive.unlink()
            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(os.dup(descriptor), "rb") as memory_archive:
                self.extract(memory_archive, destination, expected_prefix=SWIFT_NAME)
        finally:
            os.close(descriptor)

    def setup(self):
        archive = self.root / f"{SWIFT_NAME}.tar.gz"
        extracted = self.build_root / "toolchain"
        if self.fast_gaps:
            origin_receipt = self.build_root / "receipt.json"
            origin = json.loads(origin_receipt.read_text())
            if origin.get("toolchain_sha256") != SWIFT_SHA256 or origin.get("phase") != "build-complete":
                raise RuntimeError("verified_parallel_build_required_for_reuse")
            if not (extracted / ".extraction-complete").is_file():
                raise RuntimeError("verified_parallel_toolchain_missing")
            for entry in origin["native_files"]:
                if digest(self.build_root / "native" / entry["file"]) != entry["sha256"]:
                    raise RuntimeError("original_parallel_native_changed")
            self.record("reuse-verified-toolchain", toolchain_sha256=SWIFT_SHA256,
                        reused_build_root=str(self.build_root), original_parallel_receipt_sha256=digest(origin_receipt))
        if not (extracted / ".extraction-complete").exists():
            with self.request(SWIFT_URL, method="HEAD") as response:
                archive_size = int(response.headers["Content-Length"])
            with self.request(SWIFT_URL, headers={"Range": "bytes=-4"}) as response:
                if response.status != 206:
                    raise RuntimeError("toolchain_range_metadata_unavailable")
                unpacked_lower_bound = struct.unpack("<I", response.read(4))[0]
            # The full header/member check follows download; do not start a
            # download whose known minimum peak already violates either guard.
            self.guard(0 if archive.exists() else archive_size)
            self.record("download-toolchain", toolchain_url=SWIFT_URL, toolchain_archive_bytes=archive_size, toolchain_unpacked_lower_bound=unpacked_lower_bound)
            self.download(SWIFT_URL, archive, archive_size)
            signature = self.root / "swift.tar.gz.sig"
            keys = self.root / "swift-signing-keys.asc"
            self.download(SWIFT_URL + ".sig", signature, 16 * 1024)
            self.download("https://www.swift.org/keys/all-keys.asc", keys, 1024**2)
            # swift.org serves this small text resource with HTTP gzip even for
            # identity requests. urllib does not decode HTTP content encodings.
            if keys.read_bytes().startswith(b"\x1f\x8b"):
                encoded_keys = self.root / "swift-signing-keys.asc.http-gzip"
                shutil.copy2(keys, encoded_keys)
                with gzip.open(encoded_keys, "rb") as handle:
                    decoded = handle.read(1024**2 + 1)
                if len(decoded) > 1024**2 or not decoded.startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----"):
                    raise RuntimeError("invalid_signing_key_document")
                keys.write_bytes(decoded)
            gpg_home = self.root / "gnupg"
            gpg_home.mkdir(mode=0o700, exist_ok=True)
            common = ["gpg", "--homedir", str(gpg_home), "--batch", "--no-autostart"]
            self.run("import-signing-keys", [*common, "--import", str(keys)], timeout=60)
            status = self.run("verify-toolchain", [*common, "--status-fd", "1", "--verify", str(signature), str(archive)], timeout=300)
            valid = [line.split()[2] for line in status.splitlines() if line.startswith("[GNUPG:] VALIDSIG ")]
            if not valid:
                raise RuntimeError("toolchain_signature_not_valid")
            archive_hash = digest(archive)
            if archive_hash != SWIFT_SHA256:
                raise RuntimeError("pinned_toolchain_checksum_mismatch")
            self.record("toolchain-verified", toolchain_sha256=archive_hash, toolchain_signer_fingerprints=valid, signing_keys_sha256=digest(keys))
            self.extract_toolchain_in_memory(archive, extracted)
        swift = extracted / SWIFT_NAME / "usr/bin/swift"
        self.run("swift-version", [str(swift), "--version"], timeout=60)
        source_archive = self.root / "sdk-source.tar.gz"
        source_container = self.root / "source"
        if self.fast_gaps and not source_archive.exists():
            shutil.copy2(self.build_root / "sdk-source.tar.gz", source_archive)
        self.download(SOURCE_URL, source_archive, 64 * 1024**2)
        if digest(source_archive) != SOURCE_SHA256:
            raise RuntimeError("pinned_source_archive_mismatch")
        self.extract(source_archive, source_container, expected_prefix=f"desert-ant-core-{SDK_COMMIT}")
        source = source_container / f"desert-ant-core-{SDK_COMMIT}"
        model = source / "Sources/Redact/Model.swift"
        if not self.receipt.get("source_patched"):
            if digest(model) != EXPECTED_MODEL_SOURCE:
                raise RuntimeError("pinned_model_source_mismatch")
            before = model.read_text()
            needle = "        self.chunking = chunking\n"
            replacement = '''#if os(Linux) && DAL_REDACT_BENCHMARK_CHUNKING
        let benchmarkMaxChars = environmentVariable("DAL_REDACT_BENCH_MAX_CHARS")
        let benchmarkCarry = environmentVariable("DAL_REDACT_BENCH_CARRY")
        if chunking == .default && (benchmarkMaxChars != nil || benchmarkCarry != nil) {
            guard let maxChars = Int(benchmarkMaxChars ?? "150"), (150...600).contains(maxChars),
                  let carry = Int(benchmarkCarry ?? "1"), (0...1).contains(carry) else {
                throw RedactError.predictionFailed
            }
            self.chunking = Chunking(maxChars: maxChars, carry: carry)
        } else {
            self.chunking = chunking
        }
#else
        self.chunking = chunking
#endif
'''
            if before.count(needle) != 1:
                raise RuntimeError("chunking_patch_anchor_mismatch")
            after = before.replace(needle, replacement)
            model.write_text(after)
            patch = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="a/Sources/Redact/Model.swift", tofile="b/Sources/Redact/Model.swift"))
            (self.root / "benchmark-chunking.patch").write_text(patch)
            self.record("source-patched", source_patched=True, source_archive_sha256=digest(source_archive), chunking_patch_sha256=hashlib.sha256(patch.encode()).hexdigest())
        if self.parallel:
            if not self.receipt.get("fast_gaps_source_patched"):
                self.patch_parallel(source)
            if self.fast_gaps:
                self.patch_fast_gaps(source)
            self.audit_parallel_source(source)
        native = Path("/tmp/openmates-redact-inspect/redact/package/native/linux-arm64")
        litert = native / "libLiteRt.so"
        if digest(litert) != EXPECTED_LITERT:
            raise RuntimeError("litert_artifact_mismatch")
        vendor = source / "Vendor/litert/lib/linux-arm64"
        vendor.mkdir(parents=True, exist_ok=True)
        shutil.copy2(litert, vendor / litert.name)
        self.record("setup-complete", source_path=str(source), swift_path=str(swift), litert_sha256=EXPECTED_LITERT, build_requires_baseline_parity=True)
        return swift, source, vendor

    def patch_parallel(self, source: Path):
        model = source / "Sources/Redact/Model.swift"
        loading = source / "Sources/Redact/ModelLoading.swift"
        if self.receipt.get("parallel_source_patched"):
            for path in (model, loading):
                if digest(path) != self.receipt["parallel_source_sha256"][str(path.relative_to(source))]:
                    raise RuntimeError("parallel_source_changed_after_patch")
            return

        before_model, before_loading = model.read_text(), loading.read_text()

        def replace(text: str, before: str, after: str) -> str:
            if text.count(before) != 1:
                raise RuntimeError("parallel_patch_anchor_mismatch: " + before[:100])
            return text.replace(before, after)

        after_loading = replace(before_loading, "    let session: any InferenceSession\n", """    let session: any InferenceSession
#if os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL
    // Independent factory calls own independent LiteRT compiled models/locks.
    // The ordinary licensed factory path remains responsible for every load.
    private(set) var benchmarkSessions: [any InferenceSession]
#endif
""")
        after_loading = replace(after_loading, "        self.session = session\n", """        self.session = session
#if os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL
        benchmarkSessions = [session]
#endif
""")
        after_loading = replace(after_loading, "        ModelAssets(\n", "        var assets = ModelAssets(\n")
        after_loading = replace(after_loading, "                model: RedactModel.artifact, sdk: RedactModel.sdkInfo))\n", """                model: RedactModel.artifact, sdk: RedactModel.sdkInfo))
#if os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL
        guard let workers = Int(environmentVariable("DAL_REDACT_BENCH_WORKERS") ?? "1"),
              (1...8).contains(workers) else { throw RedactError.predictionFailed }
        // Finish all licensed loads before the caller supplies private text.
        for _ in 1..<workers {
            assets.benchmarkSessions.append(try await files.inferenceSession(
                model: RedactModel.artifact, sdk: RedactModel.sdkInfo))
        }
#endif
        return assets
""")
        after_model = replace(before_model, "    private let session: any InferenceSession\n", """    private let session: any InferenceSession
#if os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL
    private let benchmarkSessions: [any InferenceSession]

    // A task owns each mutable row until returning this immutable envelope.
    private final class BenchmarkChunkBatch: @unchecked Sendable {
        let rows: [(Int, [(Span, Double)])]
        init(_ rows: [(Int, [(Span, Double)])]) { self.rows = rows }
    }
#endif
""")
        after_model = replace(after_model, "        session = assets.session\n", """        session = assets.session
#if os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL
        benchmarkSessions = assets.benchmarkSessions
#endif
""")
        original_loop = """        for range in Chunks.ranges(t, chunking) {
            try await scoreChunk(t.slice(range.lowerBound, range.upperBound), at: range.lowerBound,
                                 low: low, best: &best, scored: &scored)
        }
"""
        serial_loop = original_loop.replace("low: low, best:", "low: low, session: session, best:")
        after_model = replace(after_model, original_loop, """#if os(Linux) && DAL_REDACT_BENCHMARK_PARALLEL
        if benchmarkSessions.count > 1 {
            let ranges = Chunks.ranges(t, chunking)
            let chunks = ranges.map { t.slice($0.lowerBound, $0.upperBound) }
            var ordered = [[(Span, Double)]](repeating: [], count: ranges.count)
            try await withThrowingTaskGroup(of: BenchmarkChunkBatch.self) { group in
                let count = min(benchmarkSessions.count, ranges.count)
                for worker in 0..<count {
                    let workerSession = benchmarkSessions[worker]
                    group.addTask {
                        var rows: [(Int, [(Span, Double)])] = []
                        for index in Swift.stride(from: worker, to: ranges.count, by: count) {
                            try Task.checkCancellation()
                            var localBest: [String: Int] = [:]
                            var localScored: [(Span, Double)] = []
                            try await self.scoreChunk(chunks[index], at: ranges[index].lowerBound,
                                low: low, session: workerSession,
                                best: &localBest, scored: &localScored)
                            rows.append((index, localScored))
                        }
                        return BenchmarkChunkBatch(rows)
                    }
                }
                for try await batch in group {
                    for (index, spans) in batch.rows { ordered[index] = spans }
                }
            }
            // Stable chunk order retains original first-seen order and maxima.
            // No chunk runs hysteresis, contextual rules, or final cleanup.
            for spans in ordered {
                for (span, score) in spans {
                    let key = "\\(span.start):\\(span.end):\\(span.label)"
                    if let at = best[key] {
                        if score > scored[at].1 { scored[at].1 = score }
                    } else {
                        best[key] = scored.count
                        scored.append((span, score))
                    }
                }
            }
        } else {
""" + serial_loop + """        }
#else
""" + serial_loop + """#endif
""")
        after_model = replace(after_model, "private func scoreChunk(_ text: String, at base: Int, low: Double,\n", "private func scoreChunk(_ text: String, at base: Int, low: Double, session: any InferenceSession,\n")
        after_model = replace(after_model, "runWindow(chunk, chunkOffsets)", "runWindow(chunk, chunkOffsets, session: session)")
        after_model = replace(after_model, "private func runWindow(_ chunk: [Tokenizer.Token], _ chunkOffsets: [(Int, Int)]) async throws", "private func runWindow(_ chunk: [Tokenizer.Token], _ chunkOffsets: [(Int, Int)], session: any InferenceSession) async throws")
        after_model = replace(after_model, "try await logits(ids: ids)", "try await logits(ids: ids, session: session)")
        after_model = replace(after_model, "private func logits(ids: [Int]) async throws", "private func logits(ids: [Int], session: any InferenceSession) async throws")
        with tarfile.open(self.root / "sdk-source.tar.gz", "r:gz") as archive:
            original_model = archive.extractfile(f"desert-ant-core-{SDK_COMMIT}/Sources/Redact/Model.swift").read().decode()
        patch = ""
        for path, before, after in [(model, before_model, after_model), (loading, before_loading, after_loading)]:
            relative = str(path.relative_to(source))
            if path == model:
                before = original_model
            patch += "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="a/" + relative, tofile="b/" + relative))
            path.write_text(after)
        (self.root / "benchmark-parallel.patch").write_text(patch)
        self.record("parallel-source-patched", parallel_source_patched=True,
                    parallel_patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                    parallel_source_sha256={str(path.relative_to(source)): digest(path) for path in (model, loading)})

    def patch_fast_gaps(self, source: Path):
        if self.receipt.get("fast_gaps_source_patched"):
            for relative, expected in self.receipt["parallel_source_sha256"].items():
                if digest(source / relative) != expected:
                    raise RuntimeError("fast_gaps_source_changed_after_patch")
            return
        pipeline = source / "Sources/Redact/Pipeline.swift"
        loading = source / "Sources/Redact/ModelLoading.swift"

        def replace(text: str, before: str, after: str) -> str:
            if text.count(before) != 1:
                raise RuntimeError("fast_gaps_patch_anchor_mismatch")
            return text.replace(before, after)

        after = replace(pipeline.read_text(), "enum Pipeline {\n", """enum Pipeline {
#if os(Linux) && DAL_REDACT_BENCHMARK_FAST_GAPS
    private static let benchmarkFastGaps = environmentVariable("DAL_REDACT_BENCH_FAST_GAPS") == "1"
#endif
""")
        after = replace(after, "    static func bridgeNameGaps(_ t: UTF16Text, _ spans: [Span]) -> [Span] {", """    // Source offsets and String.utf16.count use the same UTF-16 units.
    // The original string predicate always rejects gaps longer than 20.
    private static func gapIsNameLike(_ t: UTF16Text, from start: Int, to end: Int) -> Bool {
#if os(Linux) && DAL_REDACT_BENCHMARK_FAST_GAPS
        if benchmarkFastGaps && end - start > 20 { return false }
#endif
        return gapIsNameLike(t.slice(start, end))
    }

    static func bridgeNameGaps(_ t: UTF16Text, _ spans: [Span]) -> [Span] {""")
        after = replace(after, "s.start >= p.end, gapIsNameLike(t.slice(p.end, s.start))", "s.start >= p.end, gapIsNameLike(t, from: p.end, to: s.start)")
        after = replace(after, "        if hi.start < lo.end { return true }\n", """        if hi.start < lo.end { return true }
#if os(Linux) && DAL_REDACT_BENCHMARK_FAST_GAPS
        // Keep overlap first. Both original gap predicates reject >20 units.
        if benchmarkFastGaps && hi.start - lo.end > 20 { return false }
#endif
""")
        pipeline.write_text(after)
        after_loading = replace(loading.read_text(), "        guard let workers = Int(environmentVariable(\"DAL_REDACT_BENCH_WORKERS\") ?? \"1\"),", """#if DAL_REDACT_BENCHMARK_FAST_GAPS
        guard ["0", "1"].contains(environmentVariable("DAL_REDACT_BENCH_FAST_GAPS") ?? "0")
            else { throw RedactError.predictionFailed }
#endif
        guard let workers = Int(environmentVariable("DAL_REDACT_BENCH_WORKERS") ?? "1"),""")
        loading.write_text(after_loading)
        changed = ["Sources/Redact/Model.swift", "Sources/Redact/ModelLoading.swift", "Sources/Redact/Pipeline.swift"]
        patch = ""
        with tarfile.open(self.root / "sdk-source.tar.gz", "r:gz") as archive:
            for relative in changed:
                original = archive.extractfile(f"desert-ant-core-{SDK_COMMIT}/" + relative).read().decode()
                actual = (source / relative).read_text()
                patch += "".join(difflib.unified_diff(original.splitlines(keepends=True), actual.splitlines(keepends=True), fromfile="a/" + relative, tofile="b/" + relative))
        (self.root / "benchmark-parallel.patch").write_text(patch)
        self.record("fast-gaps-source-patched", fast_gaps_source_patched=True,
                    parallel_patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                    parallel_source_sha256={relative: digest(source / relative) for relative in changed})

    def audit_parallel_source(self, source: Path):
        """Prove every archive source byte and reproduce the entire allowed diff."""
        changed, unchanged, patch = [], 0, ""
        originals = {}
        with tarfile.open(self.root / "sdk-source.tar.gz", "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                relative = str(PurePosixPath(member.name).relative_to(f"desert-ant-core-{SDK_COMMIT}"))
                original = archive.extractfile(member).read()
                actual = (source / relative).read_bytes()
                if original == actual:
                    unchanged += 1
                else:
                    changed.append(relative)
                    originals[relative] = (original, actual)
        allowed = ["Sources/Redact/Model.swift", "Sources/Redact/ModelLoading.swift"]
        if self.fast_gaps:
            allowed.append("Sources/Redact/Pipeline.swift")
        if sorted(changed) != allowed:
            raise RuntimeError("parallel_source_scope_mismatch")
        for relative in sorted(changed):
            original, actual = originals[relative]
            patch += "".join(difflib.unified_diff(original.decode().splitlines(keepends=True), actual.decode().splitlines(keepends=True), fromfile="a/" + relative, tofile="b/" + relative))
        if patch != (self.root / "benchmark-parallel.patch").read_text():
            raise RuntimeError("parallel_patch_does_not_reproduce_all_source_changes")
        self.record("parallel-source-audited", source_integrity_audit={
            "unchanged_tracked_files": unchanged,
            "changed_tracked_files": sorted(changed),
            "only_benchmark_parallel_patch": True,
            "only_benchmark_parallel_fast_gaps_patch": self.fast_gaps,
            "patch_relative_to_pinned_original": True,
        })

    def build(self, swift: Path, source: Path, vendor: Path):
        stub = self.root / "link-stubs"
        stub.mkdir(exist_ok=True)
        for library, target in [("libxml2.so", "/lib/aarch64-linux-gnu/libxml2.so.2"), ("libz.so", "/lib/aarch64-linux-gnu/libz.so.1")]:
            link = stub / library
            if not link.exists():
                link.symlink_to(target)
        (stub / "libcurl.so").write_text("/* curlcompat opens the vetted host runtime */\n")
        env = dict(self.build_env)
        for key in ["DAL_WASM_BUILD", "DAL_MLX_BUILD", "SWIFT_ANDROID_STATIC_BUILD", "DAL_REDACT_BENCH_MAX_CHARS", "DAL_REDACT_BENCH_CARRY", "DAL_REDACT_BENCH_WORKERS", "DAL_REDACT_BENCH_FAST_GAPS"]:
            env.pop(key, None)
        env.update({"TMPDIR": str(self.root / "tmp"), "CLANG_MODULE_CACHE_PATH": str(self.build_root / "clang-cache"), "SWIFTPM_MODULECACHE_OVERRIDE": str(self.build_root / "swift-module-cache"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0"})
        Path(env["TMPDIR"]).mkdir(exist_ok=True)
        self.run("curlcompat", ["cc", "-c", "-fPIC", "-O2", "Tools/curlcompat/dal_curl_compat.c", "-o", str(stub / "dal_curl_compat.o")], cwd=source, env=env, timeout=60)
        command = [str(swift), "build", "--scratch-path", str(self.root / "build"), "--cache-path", str(self.root / "swiftpm-cache"), "--config-path", str(self.root / "swiftpm-config"), "--security-path", str(self.root / "swiftpm-security"), "--jobs", "4", "-c", "release", "--product", "RedactNode", "--disable-default-traits", "-Xswiftc", "-static-stdlib", "-Xswiftc", "-DDAL_REDACT_BENCHMARK_CHUNKING", "-Xlinker", f"-L{stub}", "-Xlinker", f"-L{vendor}", "-Xlinker", "-rpath", "-Xlinker", "$ORIGIN", "-Xlinker", "-z", "-Xlinker", "nodelete", "-Xlinker", str(stub / "dal_curl_compat.o")]
        if self.parallel:
            command += ["-Xswiftc", "-DDAL_REDACT_BENCHMARK_PARALLEL"]
        if self.fast_gaps:
            for index, argument in enumerate(command):
                if argument in ("--scratch-path", "--cache-path", "--config-path", "--security-path"):
                    command[index + 1] = str(self.build_root / Path(command[index + 1]).name)
            command += ["-Xswiftc", "-DDAL_REDACT_BENCHMARK_FAST_GAPS"]
        self.record("build-started", build_command=command, build_timeout_seconds=1200)
        self.run("build", command, cwd=source, env=env, timeout=1200)
        resolved = source / "Package.resolved"
        pins = json.loads(resolved.read_text()).get("pins", []) if resolved.exists() else []
        if not pins or any(pin.get("identity") != "swift-numerics" or pin.get("location") != "https://github.com/apple/swift-numerics" for pin in pins):
            raise RuntimeError("unexpected_or_unrecorded_swift_dependency")
        output = self.root / "native"
        output.mkdir(exist_ok=True)
        shutil.copy2(self.build_root / "build/release/libRedactNode.so", output / "libRedactNode.so")
        shutil.copy2(vendor / "libLiteRt.so", output / "libLiteRt.so")
        self.guard()
        native_files = [{"file": name, "bytes": (output / name).stat().st_size, "sha256": digest(output / name)}
                        for name in ["libRedactNode.so", "libLiteRt.so", "libdalcpushim.so"] if (output / name).is_file()]
        self.record("build-complete", native_path=str(output / "libRedactNode.so"), native_sha256=digest(output / "libRedactNode.so"), native_files=native_files, resolved_dependencies=pins, free_bytes=shutil.disk_usage(self.root).free, task_allocated_bytes=owned_bytes(self.root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/tmp/openmates-redact-rust-678f/swift-experiment"))
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--parallel", action="store_true", help="Build independent-session parallel experiment in a separate private child root")
    parser.add_argument("--fast-gaps", action="store_true", help="Build a separate opt-in fast-gap candidate reusing the verified parallel build toolchain/cache")
    parser.add_argument("--brotli-prefix", type=Path, default=Path("/tmp/openmates-redact-678f-brotli-1.1.1"))
    args = parser.parse_args()
    expected = Path("/tmp/openmates-redact-rust-678f/swift-experiment")
    if args.fast_gaps:
        args.parallel = True
        expected /= "parallel-fast-gaps"
    elif args.parallel:
        expected /= "parallel-experiment"
    if args.root != expected or args.root.is_symlink():
        raise RuntimeError("private_experiment_root_required")
    args.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.sched_setaffinity(0, {12, 13, 14, 15})
    os.setpriority(os.PRIO_PROCESS, 0, 10)
    experiment = Experiment(args.root, args.brotli_prefix, parallel=args.parallel, fast_gaps=args.fast_gaps)
    try:
        experiment.guard()
        swift, source, vendor = experiment.setup()
        if not args.setup_only:
            experiment.build(swift, source, vendor)
    except BaseException as error:
        experiment.record("stopped", error=str(error), free_bytes=shutil.disk_usage(args.root).free, task_allocated_bytes=owned_bytes(args.root))
        raise


if __name__ == "__main__":
    main()
