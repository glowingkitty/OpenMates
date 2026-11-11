#!/usr/bin/env bash
# Build the shared Rust client core for the Apple apps and generate its Swift
# bindings (plan apple-client-core-migration A1, D-3, D-4). One script for the
# Xcode script phase, CI and local use. Cargo output stays in the repository
# (target/apple-core); no prebuilt core is fetched or silently substituted.
#
# Usage:
#   build-xcframework.sh --xcode-phase
#   build-xcframework.sh --update-bindings | --check-bindings
#   build-xcframework.sh [--watch] [--intel] [--debug] [--framework-dir DIR] <swift-output-dir>
#   build-xcframework.sh --swift-only [--debug] <swift-output-dir>
#
# Modes:
#   --xcode-phase        Xcode pre-build script phase: build ONE static library
#                        for the active PLATFORM_NAME/ARCHS (lipo for several
#                        archs) into $DERIVED_FILE_DIR/OpenMatesCore/, always in
#                        release (debug Argon2id is unusably slow). Cargo and
#                        rustup homes default to <repo>/.tmp/apple-core-{cargo,rustup}.
#   --update-bindings    regenerate the committed bindings in apple/OpenMatesCore
#                        (Swift, C header, modulemap) from a host build (any OS)
#   --check-bindings     regenerate into a scratch directory and fail when the
#                        committed bindings in apple/OpenMatesCore differ
#   --swift-only         build only a host library and write the generated Swift
#                        to <swift-output-dir> (headers stay in the scratch dir)
#   (default)            build OpenMatesCoreFFI.xcframework (static) for every
#                        slice; proves the slices compile and prints their sizes
#
# Options for the default mode:
#   --watch              also build watchOS slices (arm64_32 + arm64 device, arm64
#                        simulator); arm64_32 uses the pinned nightly build-std recipe
#   --intel              also build x86_64 macOS and x86_64 iOS simulator slices
#   --debug              cargo dev profile instead of release (faster, larger)
#   --framework-dir DIR  where OpenMatesCoreFFI.xcframework is written
#                        (default: <repo>/target/apple-core)
set -euo pipefail
# Stays bash 3.2 compatible (macOS /bin/bash in Xcode phases): possibly empty
# arrays expand as ${a[@]+"${a[@]}"} under `set -u`, and no command substitution
# runs a build (errexit is not inherited there).

crate_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$crate_dir/../.." && pwd)"
rust_toolchain=1.98.1
watch_legacy_toolchain=nightly-2026-09-01
ffi_module=OpenMatesCoreFFI
lib_name=libopenmates_apple_bindings.a
# Committed bindings compiled straight into the app targets (apple/project.yml).
bindings_dir="$repo_dir/apple/OpenMatesCore"
bindings_swift="Sources/OpenMatesCore/OpenMatesCore.swift"
bindings_header="include/$ffi_module/$ffi_module.h"
bindings_modulemap="include/$ffi_module/module.modulemap"

mode=xcframework
watch=false
intel=false
profile=release
framework_dir="$repo_dir/target/apple-core"
swift_out=""
while (($#)); do
  case "$1" in
    --xcode-phase) mode=xcode-phase ;;
    --update-bindings) mode=update-bindings ;;
    --check-bindings) mode=check-bindings ;;
    --swift-only) mode=swift-only ;;
    --watch) watch=true ;;
    --intel) intel=true ;;
    --debug) profile=debug ;;
    --framework-dir) shift; framework_dir="${1:?--framework-dir needs a directory}" ;;
    -h|--help) sed -n '2,35p' "$0"; exit 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) [[ -z "$swift_out" ]] || { echo "Only one output directory is accepted." >&2; exit 2; }; swift_out="$1" ;;
  esac
  shift
done
case "$mode" in
  swift-only|xcframework)
    [[ -n "$swift_out" ]] || { echo "Usage: $0 [options] <swift-output-dir>" >&2; exit 2; }
    mkdir -p "$swift_out"
    swift_out="$(cd "$swift_out" && pwd)"
    ;;
  *)
    [[ -z "$swift_out" ]] || { echo "--$mode takes no output directory." >&2; exit 2; }
    ;;
esac
# The phase must never ship a dev-profile core; generation only needs metadata,
# so it shares the dev-profile build of the uniffi-bindgen run.
case "$mode" in
  xcode-phase) profile=release ;;
  update-bindings|check-bindings) profile=debug ;;
esac

if [[ "$mode" == xcode-phase ]]; then
  # Same isolation as the retired pair-login bridge: the phase keeps its own
  # cargo and rustup homes in the repository (CI caches them).
  export CARGO_HOME="${CARGO_HOME:-$repo_dir/.tmp/apple-core-cargo}"
  export RUSTUP_HOME="${RUSTUP_HOME:-$repo_dir/.tmp/apple-core-rustup}"
  mkdir -p "$CARGO_HOME" "$RUSTUP_HOME" "${DERIVED_FILE_DIR:?}/OpenMatesCore"
fi

# Xcode script phases run with a minimal PATH; rustup's default location first.
[[ -d "$HOME/.cargo/bin" ]] && export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null 2>&1; then
  echo 'build-xcframework.sh requires Rust cargo (and rustup on Apple hosts).' >&2
  exit 1
fi
if [[ "$mode" == xcode-phase ]] && ! command -v rustup >/dev/null 2>&1; then
  echo 'The OpenMatesCore build phase requires the Rust cargo and rustup tools on the Apple build host.' >&2
  exit 1
fi
cd "$repo_dir"
export CARGO_TARGET_DIR="${OPENMATES_CORE_TARGET_DIR:-$repo_dir/target/apple-core/cargo}"

# Xcode exports the SDK and deployment variables of the *current* destination;
# cargo also builds host build scripts, so drop the SDK (rustc and cc-rs ask
# xcrun per target) and pin every deployment target (apple/project.yml).
unset SDKROOT
export IPHONEOS_DEPLOYMENT_TARGET="${OPENMATES_IOS_DEPLOYMENT_TARGET:-26.2}"
export MACOSX_DEPLOYMENT_TARGET="${OPENMATES_MACOS_DEPLOYMENT_TARGET:-26.2}"
export WATCHOS_DEPLOYMENT_TARGET="${OPENMATES_WATCHOS_DEPLOYMENT_TARGET:-26.2}"

cargo_tc=()
if command -v rustup >/dev/null 2>&1; then
  rustup toolchain install "$rust_toolchain" --profile minimal --no-self-update >/dev/null
  cargo_tc=("+$rust_toolchain")
fi
profile_flag=()
[[ "$profile" == release ]] && profile_flag=(--release)

# cargo build of the static library for one target ("" = host).
build_lib() {
  local target="$1" source_std="${2:-false}" target_flag=()
  [[ -n "$target" ]] && target_flag=(--target "$target")
  echo "== openmates-apple-bindings ${target:-host} ($profile)"
  if "$source_std"; then
    # arm64_32 and x86_64 watchOS are Rust tier-3: rustup ships no std. Build
    # std from the pinned nightly source for this slice only.
    rustup toolchain install "$watch_legacy_toolchain" --profile minimal --component rust-src --no-self-update >/dev/null
    cargo "+$watch_legacy_toolchain" build -Zbuild-std=std,panic_abort -p openmates-apple-bindings \
      --lib --locked ${profile_flag[@]+"${profile_flag[@]}"} ${target_flag[@]+"${target_flag[@]}"} --quiet
  else
    if [[ -n "$target" ]] && command -v rustup >/dev/null 2>&1; then
      rustup target add "$target" --toolchain "$rust_toolchain" >/dev/null
    fi
    cargo ${cargo_tc[@]+"${cargo_tc[@]}"} build -p openmates-apple-bindings --lib --locked \
      ${profile_flag[@]+"${profile_flag[@]}"} ${target_flag[@]+"${target_flag[@]}"} --quiet
  fi
}

lib_path() {
  if [[ -n "$1" ]]; then echo "$CARGO_TARGET_DIR/$1/$profile/$lib_name"; else echo "$CARGO_TARGET_DIR/$profile/$lib_name"; fi
}

# Tokenizers links a second Rust static library into the Mac app; keep only this
# library's Rust panic personality local so the two do not collide. The UniFFI C
# ABI and every other exported symbol stay.
localize_runtime() {
  xcrun nmedit -R "$crate_dir/local-runtime-symbols.txt" "$1"
}

# Swift, C header and modulemap from the library's embedded UniFFI metadata.
generate_bindings() {
  local library="$1" out="$2"
  cargo ${cargo_tc[@]+"${cargo_tc[@]}"} run --locked -p openmates-apple-bindings --features bindgen \
    --bin uniffi-bindgen --quiet -- --swift-sources --headers --modulemap \
    --module-name "$ffi_module" --modulemap-filename module.modulemap "$library" "$out"
}

# Host build plus generation into the fresh scratch directory $scratch.
scratch="$CARGO_TARGET_DIR/bindings-generated"
generate_host_bindings() {
  build_lib ""
  rm -rf "$scratch" && mkdir -p "$scratch"
  generate_bindings "$(lib_path "")" "$scratch"
}

if [[ "$mode" == xcode-phase ]]; then
  platform="${PLATFORM_NAME:?}"
  archs="${ARCHS:-${CURRENT_ARCH:?}}"
  libraries=()
  for arch in $archs; do
    source_std=false
    case "$platform:$arch" in
      iphoneos:arm64) target=aarch64-apple-ios ;;
      iphonesimulator:arm64) target=aarch64-apple-ios-sim ;;
      iphonesimulator:x86_64) target=x86_64-apple-ios ;;
      macosx:arm64) target=aarch64-apple-darwin ;;
      macosx:x86_64) target=x86_64-apple-darwin ;;
      watchos:arm64) target=aarch64-apple-watchos ;;
      watchos:arm64_32) target=arm64_32-apple-watchos; source_std=true ;;
      watchsimulator:arm64) target=aarch64-apple-watchos-sim ;;
      watchsimulator:x86_64) target=x86_64-apple-watchos-sim; source_std=true ;;
      *) echo "Unsupported OpenMatesCore destination: $platform/$arch" >&2; exit 1 ;;
    esac
    build_lib "$target" "$source_std"
    libraries+=("$(lib_path "$target")")
  done
  output="$DERIVED_FILE_DIR/OpenMatesCore/$lib_name"
  if (( ${#libraries[@]} == 1 )); then
    cp "${libraries[0]}" "$output"
  else
    xcrun lipo -create "${libraries[@]}" -output "$output"
  fi
  [[ "$platform" == macosx ]] && localize_runtime "$output"
  exit 0
fi

if [[ "$mode" == update-bindings || "$mode" == check-bindings ]]; then
  generate_host_bindings
  pairs=(
    "OpenMatesCore.swift:$bindings_swift"
    "$ffi_module.h:$bindings_header"
    "module.modulemap:$bindings_modulemap"
  )
  stale=0
  for pair in "${pairs[@]}"; do
    generated="$scratch/${pair%%:*}"
    committed="$bindings_dir/${pair#*:}"
    if [[ "$mode" == update-bindings ]]; then
      mkdir -p "$(dirname "$committed")"
      cp "$generated" "$committed"
      echo "Updated apple/OpenMatesCore/${pair#*:}"
    elif ! cmp -s "$generated" "$committed"; then
      echo "Stale generated binding: apple/OpenMatesCore/${pair#*:}" >&2
      diff -u "$committed" "$generated" 2>&1 | head -40 >&2 || true
      stale=1
    fi
  done
  if (( stale )); then
    echo 'Regenerate with: packages/openmates-apple-bindings/build-xcframework.sh --update-bindings' >&2
    exit 1
  fi
  [[ "$mode" == check-bindings ]] && echo 'apple/OpenMatesCore bindings match the Rust crate.'
  exit 0
fi

if [[ "$mode" == swift-only ]]; then
  generate_host_bindings
  cp "$scratch/OpenMatesCore.swift" "$swift_out/"
  echo "Generated $swift_out/OpenMatesCore.swift (headers and modulemap in $scratch)"
  exit 0
fi

if ! command -v xcodebuild >/dev/null 2>&1; then
  echo 'Building the xcframework needs Xcode (xcodebuild, lipo, nmedit); use --swift-only elsewhere.' >&2
  exit 1
fi

work="$CARGO_TARGET_DIR/xcframework-work"
rm -rf "$work" && mkdir -p "$work/include/$ffi_module"

# One fat static library per xcframework slice (platform + environment).
slice() {
  local name="$1"; shift
  local libraries=() target source_std
  echo "== slice $name"
  for spec in "$@"; do
    target="${spec%%:*}"; source_std=false
    [[ "$spec" == *:std ]] && source_std=true
    build_lib "$target" "$source_std"
    libraries+=("$(lib_path "$target")")
  done
  mkdir -p "$work/$name"
  if (( ${#libraries[@]} == 1 )); then
    cp "${libraries[0]}" "$work/$name/$lib_name"
  else
    xcrun lipo -create "${libraries[@]}" -output "$work/$name/$lib_name"
  fi
}

slice ios aarch64-apple-ios
if "$intel"; then
  slice ios-simulator aarch64-apple-ios-sim x86_64-apple-ios
  slice macos aarch64-apple-darwin x86_64-apple-darwin
else
  slice ios-simulator aarch64-apple-ios-sim
  slice macos aarch64-apple-darwin
fi
if "$watch"; then
  slice watchos arm64_32-apple-watchos:std aarch64-apple-watchos
  slice watchos-simulator aarch64-apple-watchos-sim
fi

localize_runtime "$work/macos/$lib_name"

generate_bindings "$work/macos/$lib_name" "$work/generated"
cp "$work/generated/$ffi_module.h" "$work/generated/module.modulemap" "$work/include/$ffi_module/"
cp "$work/generated/OpenMatesCore.swift" "$swift_out/"

# Headers live in a module-named subdirectory so this xcframework's
# module.modulemap cannot collide with another static xcframework's in Xcode.
args=()
for name in ios ios-simulator macos watchos watchos-simulator; do
  [[ -f "$work/$name/$lib_name" ]] && args+=(-library "$work/$name/$lib_name" -headers "$work/include")
done
mkdir -p "$framework_dir"
rm -rf "$framework_dir/$ffi_module.xcframework"
xcodebuild -create-xcframework "${args[@]}" -output "$framework_dir/$ffi_module.xcframework" >/dev/null

echo "Swift bindings: $swift_out/OpenMatesCore.swift"
echo "xcframework: $framework_dir/$ffi_module.xcframework"
du -sh "$framework_dir/$ffi_module.xcframework"
for name in ios ios-simulator macos watchos watchos-simulator; do
  [[ -f "$work/$name/$lib_name" ]] && du -h "$work/$name/$lib_name" | sed "s#\t.*#\t$name#"
done
exit 0
