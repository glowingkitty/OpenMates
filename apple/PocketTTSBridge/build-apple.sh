#!/usr/bin/env bash
# Independent pinned Pocket CPU lab build. No model weights or prebuilt frameworks.
set -euo pipefail
bridge_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$bridge_dir/../.." && pwd)"
python3 "$bridge_dir/prepare.py"
export CARGO_HOME="$repo_dir/.tmp/apple-pocket-cargo"
export RUSTUP_HOME="$repo_dir/.tmp/apple-pocket-rustup"
export CARGO_BUILD_JOBS=2
export CMAKE_BUILD_PARALLEL_LEVEL=2
export CARGO_TARGET_DIR="$repo_dir/.runtime/pocket-tts/target"
mkdir -p "$CARGO_HOME" "$RUSTUP_HOME" "${DERIVED_FILE_DIR:?}/PocketTTS"
if ! command -v cargo >/dev/null 2>&1 || ! command -v rustup >/dev/null 2>&1; then
  echo 'Pocket TTS requires cargo and rustup on the build host.' >&2; exit 1
fi
rust_toolchain=1.98.1
rustup toolchain install "$rust_toolchain" --profile minimal --no-self-update >/dev/null
libraries=()
selected_slices=()
for arch in ${ARCHS:-${CURRENT_ARCH:?}}; do
  case "${PLATFORM_NAME:?}:$arch" in
    iphoneos:arm64) target=aarch64-apple-ios; toolchain=ios-device ;;
    iphonesimulator:arm64) target=aarch64-apple-ios-sim; toolchain=ios-simulator ;;
    iphonesimulator:x86_64) target=x86_64-apple-ios; toolchain=ios-simulator ;;
    macosx:arm64) target=aarch64-apple-darwin; toolchain=mac ;;
    macosx:x86_64) target=x86_64-apple-darwin; toolchain=mac ;;
    *) echo "Unsupported Pocket lab destination: $PLATFORM_NAME/$arch" >&2; exit 1 ;;
  esac
  rustup target add "$target" --toolchain "$rust_toolchain" >/dev/null
  if [[ "$toolchain" != mac ]]; then
    export CMAKE_OSX_ARCHITECTURES="$arch"
    export CMAKE_TOOLCHAIN_FILE="$bridge_dir/$toolchain.cmake"
    export POCKET_APPLE_ARCH="$arch"
    # Nested Xcode generators reuse the outer app build service and can crash.
    # Makefiles invoke clang/libtool directly with this slice's cross toolchain.
    export CMAKE_GENERATOR="Unix Makefiles"
  else
    unset CMAKE_TOOLCHAIN_FILE POCKET_APPLE_ARCH CMAKE_GENERATOR || true
    export CMAKE_OSX_ARCHITECTURES="$arch"
  fi
  # CMake cannot change generators in place. Preserve the former generated
  # Xcode CMake tree, and reconfigure only SentencePiece; all Cargo artifacts,
  # source caches and root verification receipts stay in place.
  if [[ "$toolchain" != mac ]]; then
    python3 - "$CARGO_TARGET_DIR/$target/release/build" <<'PYTHON'
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
if root.exists():
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise SystemExit("Pocket Cargo cache path must not contain links")
    for cache in root.glob("sentencepiece-sys-*/out/build/CMakeCache.txt"):
        if cache.is_symlink() or any(parent.is_symlink() for parent in cache.parents):
            raise SystemExit("Pocket CMake cache path must not contain links")
        if cache.stat().st_size > 1024 * 1024:
            raise SystemExit("Pocket CMake cache exceeds expected size")
        generator = next((line.split("=", 1)[1] for line in cache.read_text().splitlines()
                          if line.startswith("CMAKE_GENERATOR:INTERNAL=")), None)
        if generator == "Xcode":
            retired = cache.parent.with_name("build-xcode-retired")
            if retired.exists() or retired.is_symlink():
                raise SystemExit("Pocket retired CMake cache already exists; review before retrying")
            cache.parent.rename(retired)
PYTHON
  fi
  cargo "+$rust_toolchain" build --manifest-path "$bridge_dir/Cargo.toml" --locked --jobs 2 --release --target "$target" --quiet
  libraries+=("$CARGO_TARGET_DIR/$target/release/libopenmates_pocket_tts.a")
  selected_slices+=("$arch" "$CARGO_TARGET_DIR/$target/release/libopenmates_pocket_tts.a")
done
output="$DERIVED_FILE_DIR/PocketTTS/libopenmates_pocket_tts.a"
# Package runtime symbols even when Cargo reuses its compiled archive. Never
# reuse the prior DerivedSources output as a completed packaging receipt.
if [[ "$PLATFORM_NAME" == macosx ]]; then
  python3 - "$output" "$bridge_dir/local-runtime-symbols.txt" "${selected_slices[@]}" <<'PYTHON'
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

archive = pathlib.Path(sys.argv[1])
personality_file = pathlib.Path(sys.argv[2])
# Inspect native Mach-O tables, not embedded LLVM IR. Apple's LLVM reader may
# predate Rust's LLVM version; the native linker consumes these Mach-O symbols.
def symbols(path, *flags):
    result = subprocess.run(["xcrun", "nm", "--no-llvm-bc", "--quiet", "-j", *flags, str(path)],
                            check=True, capture_output=True, text=True)
    return set(result.stdout.splitlines())

pattern = re.compile(r"__RNvNtCs[0-9A-Za-z]+_3std9panicking11EMPTY_PANIC")
# EMPTY_PANIC is a compiler-retained function pointer in std. Pair's fat LTO
# emits the same std identity into its bridge object, creating a strong-symbol
# collision. Localizing a definition needed by another archive member would
# break resolution, so reject that case before modifying the copied archive.
abi = {"_om_pocket_create", "_om_pocket_synthesize", "_om_pocket_audio_bytes",
       "_om_pocket_audio_count", "_om_pocket_audio_free", "_om_pocket_destroy"}
personality = {line.strip() for line in personality_file.read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")}
if personality != {"_rust_eh_personality"}:
    raise SystemExit("Unexpected Pocket runtime personality localization policy")
# Rust identities differ between architectures. A union of their removal lists
# fails nmedit when a symbol is absent from another slice. Work only on temporary
# copies, validate every slice before editing, and publish after lipo verification.
slice_arguments = sys.argv[3:]
if not slice_arguments or len(slice_arguments) % 2:
    raise SystemExit("Pocket Mac packaging requires architecture/archive pairs")
with tempfile.TemporaryDirectory(prefix=".runtime-slices-", dir=archive.parent) as staging:
    root = pathlib.Path(staging)
    slices = []
    seen = set()
    for arch, source in zip(slice_arguments[::2], slice_arguments[1::2]):
        if arch not in {"arm64", "x86_64"} or arch in seen:
            raise SystemExit("Unexpected or duplicate Pocket Mac architecture")
        seen.add(arch)
        path = root / f"{arch}.a"
        shutil.copyfile(source, path)
        exports = symbols(path, "-gU")
        panic_statics = {name for name in exports if pattern.fullmatch(name)}
        if not panic_statics:
            raise SystemExit(f"Pocket Mac {arch} archive lacks the expected pinned Rust EMPTY_PANIC symbol")
        if panic_statics & symbols(path, "-gu"):
            raise SystemExit(f"Pocket EMPTY_PANIC has cross-object references in {arch}; review runtime packaging")
        if not abi <= exports:
            raise SystemExit(f"Pocket {arch} archive lacks a required public C ABI symbol")
        slices.append((arch, path, exports, panic_statics | personality))
    for arch, path, exports, localized in slices:
        names = root / f"{arch}-runtime-symbols.txt"
        names.write_text("\n".join(sorted(localized)) + "\n")
        subprocess.run(["xcrun", "nmedit", "-R", str(names), str(path)], check=True)
        if symbols(path, "-gU") != exports - localized:
            raise SystemExit(f"Pocket {arch} runtime localization changed unexpected exported symbols")
    if len(slices) == 1:
        staged_output = slices[0][1]
    else:
        staged_output = root / "universal.a"
        subprocess.run(["xcrun", "lipo", "-create", *[str(item[1]) for item in slices],
                        "-output", str(staged_output)], check=True)
        for arch, _, exports, localized in slices:
            verification = root / f"{arch}-combined.a"
            subprocess.run(["xcrun", "lipo", "-thin", arch, str(staged_output),
                            "-output", str(verification)], check=True)
            if symbols(verification, "-gU") != exports - localized:
                raise SystemExit(f"Pocket {arch} combined archive changed unexpected exported symbols")
    staged_output.replace(archive)
PYTHON
else
  # Preserve the existing iOS device/simulator packaging policy.
  if (( ${#libraries[@]} == 1 )); then cp "${libraries[0]}" "$output"
  else xcrun lipo -create "${libraries[@]}" -output "$output"; fi
  xcrun nmedit -R "$bridge_dir/local-runtime-symbols.txt" "$output"
fi
