#!/usr/bin/env bash
# Build the pinned Rust PAKE binding for the active Xcode target/architecture.
# Cargo downloads and outputs stay in this repository; no prebuilt opaque code is
# fetched or silently substituted.
set -euo pipefail

bridge_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$bridge_dir/../.." && pwd)"
export CARGO_TARGET_DIR="$bridge_dir/target"
export CARGO_HOME="${CARGO_HOME:-$repo_dir/.tmp/apple-pair-cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-$repo_dir/.tmp/apple-pair-rustup}"
mkdir -p "$CARGO_HOME" "$RUSTUP_HOME" "${DERIVED_FILE_DIR:?}/PairOpaque"

if ! command -v cargo >/dev/null 2>&1 || ! command -v rustup >/dev/null 2>&1; then
  echo 'PairOpaqueBridge requires the Rust cargo and rustup tools on the Apple build host.' >&2
  exit 1
fi

rust_toolchain=1.98.1
watch_legacy_toolchain=nightly-2026-09-01
rustup toolchain install "$rust_toolchain" --profile minimal --no-self-update >/dev/null

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
    *) echo "Unsupported PairOpaqueBridge destination: $platform/$arch" >&2; exit 1 ;;
  esac
  if "$source_std"; then
    # arm64_32 is a Rust tier-3 target: rustc recognizes the ABI, but rustup
    # does not ship std. Build std from the pinned nightly source for this slice.
    rustup toolchain install "$watch_legacy_toolchain" --profile minimal --component rust-src --no-self-update >/dev/null
    cargo "+$watch_legacy_toolchain" build -Zbuild-std=std,panic_abort \
      --manifest-path "$bridge_dir/Cargo.toml" --locked --release --target "$target" --quiet
  else
    rustup target add "$target" --toolchain "$rust_toolchain" >/dev/null
    cargo "+$rust_toolchain" build --manifest-path "$bridge_dir/Cargo.toml" --locked --release --target "$target" --quiet
  fi
  libraries+=("$CARGO_TARGET_DIR/$target/release/libopenmates_pair_opaque.a")
done

output="$DERIVED_FILE_DIR/PairOpaque/libopenmates_pair_opaque.a"
if (( ${#libraries[@]} == 1 )); then
  cp "${libraries[0]}" "$output"
else
  xcrun lipo -create "${libraries[@]}" -output "$output"
fi
