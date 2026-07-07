#!/usr/bin/env bash
# =============================================================================
# OpenMates Vercel build cost guard
#
# Vercel's ignoreCommand contract is inverted:
#   exit 0 -> ignore this deployment and do not run the build
#   exit 1 -> continue with the build
#
# We block Vercel builds by default to prevent unexpected build CPU charges.
# To intentionally allow builds, set OPENMATES_ALLOW_VERCEL_BUILD=1 in the
# Vercel deployment environment. Commit messages must never opt into builds;
# mentioning an escape hatch in documentation should not burn build minutes.
# =============================================================================
set -euo pipefail

if [[ "${OPENMATES_ALLOW_VERCEL_BUILD:-}" == "1" ]]; then
  echo "[vercel-ignore] OPENMATES_ALLOW_VERCEL_BUILD=1, allowing Vercel build."
  exit 1
fi

echo "[vercel-ignore] Vercel builds are disabled by default to prevent unexpected build CPU charges."
echo "[vercel-ignore] Set OPENMATES_ALLOW_VERCEL_BUILD=1 in Vercel only when a deliberate build is needed."
exit 0
