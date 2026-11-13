#!/usr/bin/env bash
# Prepare a fresh checkout for a local Xcode build of the Apple apps on a Mac.
#
# Runs the same preparation as the GitHub macos-26 Apple lanes (scripts/ci_apple.py):
# generated design tokens and locales (not committed), the pinned Whistle link
# inputs, and the Rust toolchain used by the "Build OpenMatesCore" Xcode phase.
# The UniFFI Swift bindings are committed in apple/OpenMatesCore; the Xcode
# phase builds the Rust static library itself on every build.
#
# Usage: scripts/apple_local_prepare.sh [--check]
#   --check   only report missing prerequisites, change nothing
#
# Stays bash 3.2 compatible (macOS /bin/bash).
set -euo pipefail

log() { printf '[openmates:prepare] %s\n' "$*"; }
die() { printf '[openmates:prepare] error: %s\n' "$*" >&2; exit 1; }

check_only=false
case "${1:-}" in
  --check) check_only=true ;;
  '') ;;
  -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
  *) die "unknown option: $1" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
[[ "$(uname -s)" == Darwin ]] || die "run this on a Mac (the Apple build needs Xcode)"

missing=0
need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[openmates:prepare] missing: %s (%s)\n' "$1" "$2" >&2
    missing=1
  fi
}
[[ -d "$HOME/.cargo/bin" ]] && export PATH="$HOME/.cargo/bin:$PATH"
need xcodebuild "install Xcode 26.2 or newer and run: sudo xcode-select -s /Applications/Xcode.app"
need python3 "ships with the Xcode command line tools"
need node "Node.js 20 or newer, e.g. brew install node"
need npm "comes with Node.js"
need rustup "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal"
[[ "$missing" -eq 0 ]] || die "install the missing tools above, then run this script again"

xcode_version="$(xcodebuild -version | sed -n 's/^Xcode //p')"
xcode_major="${xcode_version%%.*}"
xcode_minor="$(printf '%s' "$xcode_version" | cut -d. -f2)"
if [[ "$xcode_major" -lt 26 || ( "$xcode_major" -eq 26 && "${xcode_minor:-0}" -lt 2 ) ]]; then
  die "Xcode $xcode_version found; the apps target iOS/macOS/watchOS 26.2 and need Xcode 26.2 or newer"
fi
log "Xcode $xcode_version, $(node --version), $(rustup --version 2>/dev/null | head -1)"

if [[ "$check_only" == true ]]; then
  log "prerequisites present (--check: nothing changed)"
  exit 0
fi

ui=frontend/packages/ui
if [[ ! -d "$ui/node_modules/yaml" || ! -d "$ui/node_modules/@lucide/svelte" || ! -d "$ui/node_modules/@meteocons" ]]; then
  # Same minimal install as CI: the generators need only these three packages.
  log "installing the token generator dependencies"
  deps_dir="$repo_root/.tmp/apple-token-deps"
  specs="$(node -e "const p=require('./$ui/package.json');const d={...p.dependencies,...p.devDependencies};console.log(['yaml','@lucide/svelte','@meteocons/svg'].map(n=>n+'@'+d[n]).join(' '))")"
  # shellcheck disable=SC2086 # $specs is a space-separated package list
  npm install --prefix "$deps_dir" --no-save --no-package-lock --legacy-peer-deps \
    --ignore-scripts --no-audit --no-fund $specs
  mkdir -p "$ui/node_modules/@lucide"
  [[ -e "$ui/node_modules/yaml" ]] || ln -s "$deps_dir/node_modules/yaml" "$ui/node_modules/yaml"
  [[ -e "$ui/node_modules/@lucide/svelte" ]] || ln -s "$deps_dir/node_modules/@lucide/svelte" "$ui/node_modules/@lucide/svelte"
  [[ -e "$ui/node_modules/@meteocons" ]] || ln -s "$deps_dir/node_modules/@meteocons" "$ui/node_modules/@meteocons"
fi

log "generating design tokens and locales"
(cd "$ui" && node scripts/build-tokens.js >/dev/null && node scripts/build-translations.js >/dev/null)
[[ -f "$ui/src/tokens/generated/swift/ColorTokens.generated.swift" ]] || die "token generation produced no Swift tokens"

log "preparing the pinned Whistle link inputs (downloads the pinned assets once)"
python3 apple/WhistleBridge/prepare-build.py --fetch >/dev/null

# The Xcode phase installs these into <repo>/.tmp/apple-core-rustup on first
# build; doing it here keeps the first Xcode build from looking stuck.
rust_toolchain="$(sed -n 's/^rust_toolchain=//p' packages/openmates-apple-bindings/build-xcframework.sh)"
export CARGO_HOME="$repo_root/.tmp/apple-core-cargo" RUSTUP_HOME="$repo_root/.tmp/apple-core-rustup"
mkdir -p "$CARGO_HOME" "$RUSTUP_HOME"
log "installing Rust $rust_toolchain with the Apple targets into .tmp (first run takes a few minutes)"
rustup toolchain install "$rust_toolchain" --profile minimal --no-self-update \
  --target aarch64-apple-darwin --target aarch64-apple-ios --target aarch64-apple-ios-sim \
  --target aarch64-apple-watchos --target aarch64-apple-watchos-sim >/dev/null

log "ready. Open apple/OpenMates.xcodeproj and run OpenMates_macOS (My Mac) or OpenMates_iOS."
