#!/usr/bin/env python3
"""Build/verify an isolated patched decoder; never create a model or issue HTTP via SDK."""
from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

VERSION = "1.1.1"
VERSION_NUMBER = (1 << 24) | (1 << 12) | 1
COMMIT = "db0631dfea829194206d269bc7b25d0908cdb97d"
ARCHIVE_SHA256 = "38f9c17ee36c2e930ce00975b50fcd246a8e5594c1bcf43cd56b14118786b82a"
DECODER_SOURCE_SHA256 = "79db5a1879540eb7c915ce948e8fb94adc1ff49be87dca01529b9283c6ba343e"
LIBRARIES = ("libbrotlicommon.so.1", "libbrotlidec.so.1")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_source(source):
    decoder = source / "c/dec/decode.c"
    if digest(decoder) != DECODER_SOURCE_SHA256:
        raise ValueError("Patched decoder source hash mismatch")
    text = decoder.read_text()
    if not all(marker in text for marker in (
        "if (max_block_type <= 1)", "return BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH;",
        "BROTLI_SAFE_WITH_STATUS(DecodeCommandBlockSwitch(s))",
        "BROTLI_SAFE_WITH_STATUS(DecodeDistanceBlockSwitch(s))",
        "BROTLI_SAFE_WITH_STATUS(DecodeLiteralBlockSwitch(s))")):
        raise ValueError("Patched block-switch error propagation missing")


def build(prefix):
    """Compile only common+decoder with existing cc; no packages/system writes."""
    compiler = shutil.which("cc")
    if not compiler:
        raise ValueError("Existing C compiler required; no automatic installation")
    prefix = prefix.resolve()
    if str(prefix).startswith(("/usr/", "/lib/", "/opt/")):
        raise ValueError("Build prefix must be task-private")
    prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = prefix / "source.tar.gz"
    if not archive.exists():
        request = urllib.request.Request(
            f"https://codeload.github.com/google/brotli/tar.gz/{COMMIT}",
            headers={"User-Agent": "OpenMates-Private-Brotli-Build/1.0", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(16 * 1024**2 + 1)
        if len(data) > 16 * 1024**2 or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Pinned official source archive integrity failed")
        archive.write_bytes(data)
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("Pinned official source archive integrity failed")
    source = prefix / f"brotli-{COMMIT}"
    if not source.exists():
        with tarfile.open(fileobj=io.BytesIO(archive.read_bytes()), mode="r:gz") as bundle:
            bundle.extractall(prefix, filter="data")
    verify_source(source)
    # Reject modified non-decoder sources too, using the exact pinned archive.
    with tarfile.open(fileobj=io.BytesIO(archive.read_bytes()), mode="r:gz") as bundle:
        for entry in bundle.getmembers():
            if entry.isfile():
                expected = bundle.extractfile(entry).read()
                if (prefix / entry.name).read_bytes() != expected:
                    raise ValueError("Extracted source differs from pinned archive")
    cpus = sorted(os.sched_getaffinity(0))[:2]
    os.sched_setaffinity(0, cpus)
    os.nice(10)
    lib = prefix / "lib"
    lib.mkdir(exist_ok=True)
    commands = []
    for component in ("common", "dec"):
        name = "brotli" + component
        target = lib / f"lib{name}.so.{VERSION}"
        command = [compiler, "-O2", "-DNDEBUG", "-fPIC", "-fvisibility=hidden",
                   "-DBROTLI_SHARED_COMPILATION", f"-D{name.upper()}_SHARED_COMPILATION",
                   "-I", str(source / "c/include"), "-shared", f"-Wl,-soname,lib{name}.so.1",
                   "-o", str(target), *map(str, sorted((source / "c" / component).glob("*.c")))]
        if component == "dec":
            command += ["-L", str(lib), "-lbrotlicommon", "-Wl,-rpath,$ORIGIN"]
        command += ["-lm"]
        subprocess.run(command, check=True, timeout=120, capture_output=True)
        for suffix in (".so", ".so.1"):
            link = lib / f"lib{name}{suffix}"
            if not link.exists():
                link.symlink_to(target.name)
        commands.append(command)
    receipt = {"schema": 1, "version": VERSION, "commit": COMMIT,
               "archive_sha256": ARCHIVE_SHA256, "decoder_source_sha256": DECODER_SOURCE_SHA256,
               "fixed_block_switch_error_propagation": True, "compiler": compiler,
               "compiler_version": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
               "build_commands": commands, "affinity_cpus": cpus, "niceness_increment": 10,
               "libraries": {name: {"file": str((lib / name).resolve().relative_to(prefix)),
                                    "sha256": digest(lib / name)} for name in LIBRARIES}}
    (prefix / "security-build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return verify_prefix(prefix)


def verify_prefix(prefix):
    prefix = prefix.resolve()
    receipt = json.loads((prefix / "security-build.json").read_text())
    expected = {"schema": 1, "version": VERSION, "commit": COMMIT,
                "archive_sha256": ARCHIVE_SHA256, "decoder_source_sha256": DECODER_SOURCE_SHA256,
                "fixed_block_switch_error_propagation": True}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("Verified patched Brotli build receipt required")
    verify_source(prefix / f"brotli-{COMMIT}")
    for name in LIBRARIES:
        library = (prefix / "lib" / name).resolve()
        entry = receipt["libraries"][name]
        if not library.is_relative_to(prefix / "lib") or entry["file"] != str(library.relative_to(prefix)):
            raise ValueError("Decoder library escapes task-private prefix")
        if digest(library) != entry["sha256"]:
            raise ValueError("Decoder library hash mismatch")
    return receipt


def child_environment(prefix, env):
    verify_prefix(prefix)
    if env.get("LD_PRELOAD") or env.get("LD_AUDIT"):
        raise ValueError("Loader interposition is not allowed in verified evaluator")
    return {**env, "LD_LIBRARY_PATH": str(prefix.resolve() / "lib"),
            "OPENMATES_REDACT_BROTLI_PREFIX": str(prefix.resolve())}


def deny_network():
    lib = c.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = [c.c_uint32]
    lib.seccomp_init.restype = c.c_void_p
    lib.seccomp_attr_set.argtypes = [c.c_void_p, c.c_int, c.c_uint32]
    lib.seccomp_syscall_resolve_name.argtypes = [c.c_char_p]
    lib.seccomp_rule_add.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.c_uint]
    lib.seccomp_load.argtypes = [c.c_void_p]
    lib.seccomp_release.argtypes = [c.c_void_p]
    ctx = lib.seccomp_init(0x7FFF0000)
    if not ctx:
        raise ValueError("Preflight network seal unavailable")
    try:
        if lib.seccomp_attr_set(ctx, 4, 1):
            raise ValueError("Preflight TSYNC unavailable")
        for name in (b"socket", b"socketpair", b"connect", b"sendto", b"sendmsg", b"sendmmsg"):
            syscall = lib.seccomp_syscall_resolve_name(name)
            if syscall < 0 or lib.seccomp_rule_add(ctx, 0x00050001, syscall, 0):
                raise ValueError("Preflight deny rule failed")
        if lib.seccomp_load(ctx):
            raise ValueError("Preflight network seal failed")
    finally:
        lib.seccomp_release(ctx)


def probe(prefix, native_core):
    """Check the actual SDK shim -> deep-bound curl dependency graph, offline."""
    receipt = verify_prefix(prefix)
    if os.environ.get("LD_LIBRARY_PATH") != str(prefix.resolve() / "lib"):
        raise ValueError("Private decoder must be selected before process startup")
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    os.nice(10)
    deny_network()
    core = c.CDLL(str(native_core.resolve()))
    core.dal_curl_available.restype = c.c_int
    if core.dal_curl_available() != 1:
        raise ValueError("SDK curl shim unavailable")
    curl = c.CDLL("libcurl.so.4", mode=os.RTLD_NOW | os.RTLD_LOCAL | os.RTLD_NOLOAD)
    curl.BrotliDecoderVersion.restype = c.c_uint32
    if curl.BrotliDecoderVersion() != VERSION_NUMBER:
        raise ValueError("SDK libcurl resolved an unapproved decoder version")
    libc = c.CDLL(None)

    class DlInfo(c.Structure):
        _fields_ = [("filename", c.c_char_p), ("base", c.c_void_p),
                    ("symbol", c.c_char_p), ("symbol_address", c.c_void_p)]

    libc.dladdr.argtypes = [c.c_void_p, c.POINTER(DlInfo)]
    symbols = {}
    for name in ("BrotliDecoderVersion", "BrotliDecoderDecompressStream"):
        address = c.cast(getattr(curl, name), c.c_void_p).value
        info = DlInfo()
        if not libc.dladdr(address, c.byref(info)):
            raise ValueError("Decoder symbol mapping unavailable")
        library = Path(os.fsdecode(info.filename)).resolve()
        expected = (prefix / receipt["libraries"]["libbrotlidec.so.1"]["file"]).resolve()
        if library != expected:
            raise ValueError("SDK curl decoder symbol mapped outside verified prefix")
        symbols[name] = {"address": hex(address), "library": str(library), "sha256": digest(library)}
    mapped = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines()
                     if "/libbrotli" in line})
    if any(not Path(file).resolve().is_relative_to(prefix / "lib") for file in mapped):
        raise ValueError("Unapproved system Brotli library mapped")
    curl.curl_easy_init.restype = c.c_void_p
    curl.curl_easy_cleanup.argtypes = [c.c_void_p]
    handle = curl.curl_easy_init()
    if not handle:
        raise ValueError("Offline curl initialization failed")
    curl.curl_easy_cleanup(handle)
    curl.curl_version.restype = c.c_char_p
    return {"status": "verified", "version": VERSION, "version_number": VERSION_NUMBER,
            "commit": COMMIT, "prefix": str(prefix.resolve()), "symbols": symbols,
            "mapped_brotli_libraries": mapped, "curl_version": curl.curl_version().decode(),
            "network": "libseccomp TSYNC deny installed before SDK library load; no HTTP perform",
            "sdk_model_or_license_created": False, "curl_init_cleanup": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--native-core", type=Path)
    args = parser.parse_args()
    if args.build:
        result = build(args.prefix)
    elif args.probe and args.native_core:
        result = probe(args.prefix, args.native_core)
    else:
        result = verify_prefix(args.prefix)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
