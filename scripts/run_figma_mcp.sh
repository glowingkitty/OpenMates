#!/usr/bin/env bash
# Launch the pinned Figma MCP server with the private local credential.
# The token stays in .env.figma.local and is never embedded in OpenCode config,
# command arguments, repository files, or generated design indexes.

set -euo pipefail

CHECKOUT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! GIT_COMMON_DIR="$(git -C "${CHECKOUT_ROOT}" rev-parse --git-common-dir 2>/dev/null)"; then
	printf 'Cannot resolve the OpenMates control-plane checkout from %s.\n' "${CHECKOUT_ROOT}" >&2
	exit 2
fi
if [[ "${GIT_COMMON_DIR}" != /* ]]; then
	GIT_COMMON_DIR="$(cd "${CHECKOUT_ROOT}/${GIT_COMMON_DIR}" && pwd)"
fi
if [[ "${GIT_COMMON_DIR}" != */.git ]]; then
	printf 'Unexpected Git common directory for Figma MCP: %s\n' "${GIT_COMMON_DIR}" >&2
	exit 2
fi
CONTROL_PLANE_ROOT="${GIT_COMMON_DIR%/.git}"
TOKEN_FILE="${CONTROL_PLANE_ROOT}/.env.figma.local"

if [[ -z "${FIGMA_ACCESS_TOKEN:-}" && -f "${TOKEN_FILE}" ]]; then
	set -a
	# shellcheck disable=SC1090 -- the private env file is intentionally local.
	source "${TOKEN_FILE}"
	set +a
fi

if [[ -z "${FIGMA_ACCESS_TOKEN:-}" ]]; then
	printf 'Missing FIGMA_ACCESS_TOKEN in %s or the process environment.\n' "${TOKEN_FILE}" >&2
	exit 2
fi

export FIGMA_API_KEY="${FIGMA_ACCESS_TOKEN}"
unset FIGMA_ACCESS_TOKEN

# Newer releases resolve posthog-node versions that require Node 22.22+, while
# the OpenCode host currently runs Node 22.19. Keep this working pin explicit.
exec npx -y figma-developer-mcp@0.9.0 --stdio
