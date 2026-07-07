#!/usr/bin/env bash
# =============================================================================
# OpenMates Vercel build cost guard
#
# Vercel's ignoreCommand contract is inverted:
#   exit 0 -> ignore this deployment and do not run the build
#   exit 1 -> continue with the build
#
# We block Vercel builds by default to prevent unexpected build CPU charges.
# To intentionally allow one build, set OPENMATES_ALLOW_VERCEL_BUILD=1 in the
# Vercel deployment environment or include [vercel-build] in the commit message.
# =============================================================================
set -euo pipefail

if [[ "${OPENMATES_ALLOW_VERCEL_BUILD:-}" == "1" ]]; then
  echo "[vercel-ignore] OPENMATES_ALLOW_VERCEL_BUILD=1, allowing Vercel build."
  exit 1
fi

commit_message="${VERCEL_GIT_COMMIT_MESSAGE:-}"
if [[ "$commit_message" == *"[vercel-build]"* ]]; then
  echo "[vercel-ignore] Commit message contains [vercel-build], allowing Vercel build."
  exit 1
fi

echo "[vercel-ignore] Vercel builds are disabled by default to prevent unexpected build CPU charges."
echo "[vercel-ignore] Set OPENMATES_ALLOW_VERCEL_BUILD=1 or include [vercel-build] to allow a deliberate build."
exit 0
