#!/usr/bin/env bash
# Restrict only this static library's Rust panic personality to local linkage.
set -euo pipefail
if [[ "${PLATFORM_NAME:?}" != macosx ]]; then
  exit 0
fi
bridge_dir="$(cd "$(dirname "$0")" && pwd)"
# Preserve the pair_opaque_call/free C ABI and every other exported symbol.
# Tokenizers supplies a separate Rust personality in the same Mac executable.
xcrun nmedit -R "$bridge_dir/local-runtime-symbols.txt" "${1:?static library required}"
