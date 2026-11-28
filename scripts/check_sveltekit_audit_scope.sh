#!/usr/bin/env bash
# GHSA-3r8g-jcqq-3p5j applies when experimental remote functions are enabled.
set -euo pipefail

if git grep -n -w remoteFunctions -- 'frontend/*.js' 'frontend/*.ts' 'frontend/*.mjs' 'frontend/*.cjs' 'frontend/*.mts' 'frontend/*.cts'; then
  echo "Upgrade SvelteKit and remove the GHSA-3r8g-jcqq-3p5j exception before enabling remote functions." >&2
  exit 1
else
  grep_status=$?
  if [[ "$grep_status" != 1 ]]; then
    exit "$grep_status"
  fi
fi

remote_modules=$(git ls-files 'frontend/*.remote.*')
if [[ -n "$remote_modules" ]]; then
  printf 'Upgrade SvelteKit and remove the advisory exception before adding remote modules:\n%s\n' "$remote_modules" >&2
  exit 1
fi
