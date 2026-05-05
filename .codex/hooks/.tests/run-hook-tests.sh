#!/bin/bash
# Test harness for the 10 hooks added under OPE-375.
# Usage: bash .claude/hooks/.tests/run-hook-tests.sh
# Each case feeds a crafted stdin JSON payload to a hook and asserts on
# its exit code and stderr content. Runs with `set -u` off so we can
# still count failures from inside nested loops.

set -eo pipefail
cd "$(dirname "$0")/../../.."   # project root

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
PASS=0; FAIL=0
FAILS=()

# run_case NAME HOOK INPUT_JSON EXPECT_EXIT EXPECT_STDERR_PATTERN
run_case() {
  local name="$1" hook="$2" input="$3" exp_exit="$4" exp_pattern="$5"
  local stderr rc
  stderr=$(echo "$input" | bash ".claude/hooks/$hook" 2>&1 >/dev/null)
  rc=$?
  if [ "$rc" -ne "$exp_exit" ]; then
    echo -e "${RED}FAIL${NC} $name — expected exit $exp_exit, got $rc"
    FAILS+=("$name (exit $rc vs $exp_exit)"); FAIL=$((FAIL+1)); return
  fi
  if [ -n "$exp_pattern" ]; then
    if ! echo "$stderr" | grep -qE "$exp_pattern"; then
      echo -e "${RED}FAIL${NC} $name — stderr did not match /$exp_pattern/"
      echo "  stderr: $stderr" | head -3
      FAILS+=("$name (pattern)"); FAIL=$((FAIL+1)); return
    fi
  else
    if [ -n "$stderr" ]; then
      echo -e "${RED}FAIL${NC} $name — expected empty stderr, got: $stderr"
      FAILS+=("$name (unexpected stderr)"); FAIL=$((FAIL+1)); return
    fi
  fi
  echo -e "${GREEN}PASS${NC} $name"
  PASS=$((PASS+1))
}

echo "=== Hook #1: provider-registry-sync ==="
# Negative: adding vercel (already in policy) → quiet
run_case "provider-sync: known provider (vercel) silent" \
  "provider-registry-sync.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/home/superdev/projects/OpenMates/backend/shared/providers/openai/client.py","new_string":"import openai\nclient = openai.Client()"}}' \
  0 ""
# Positive: adding mixpanel (not in policy) → warning
run_case "provider-sync: unknown provider (mixpanel) warns" \
  "provider-registry-sync.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/home/superdev/projects/OpenMates/backend/apps/foo/bar.py","new_string":"import mixpanel\nmixpanel.track(\"event\")"}}' \
  0 "provider.*not disclosed"
# Negative: non-python file ignored
run_case "provider-sync: non-code file ignored" \
  "provider-registry-sync.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/home/superdev/projects/OpenMates/README.md","new_string":"import mixpanel"}}' \
  0 ""

echo ""
echo "=== Hook #2: analytics-sdk-forbidden ==="
# Positive: adding posthog
run_case "analytics-forbidden: posthog in .ts warns" \
  "analytics-sdk-forbidden.sh" \
  '{"tool_name":"Write","tool_input":{"file_path":"/tmp/foo.ts","content":"import posthog from \"posthog-js\";\nposthog.init(\"KEY\");"}}' \
  0 "analytics.*SDK"
# Negative: clean code
run_case "analytics-forbidden: clean code silent" \
  "analytics-sdk-forbidden.sh" \
  '{"tool_name":"Write","tool_input":{"file_path":"/tmp/foo.ts","content":"export const x = 1;"}}' \
  0 ""
# Positive: gtag( in html
run_case "analytics-forbidden: gtag call warns" \
  "analytics-sdk-forbidden.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.js","new_string":"gtag(\"config\", \"GA-XXX\");"}}' \
  0 "analytics"

echo ""
echo "=== Hook #3: css-selector-in-specs ==="
# Positive: .class selector in spec
run_case "css-selector-specs: .class warn" \
  "css-selector-in-specs.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.spec.ts","new_string":"await page.locator(\".send-button\").click();"}}' \
  0 "data-testid"
# Negative: data-testid usage clean
run_case "css-selector-specs: getByTestId silent" \
  "css-selector-in-specs.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.spec.ts","new_string":"await page.getByTestId(\"send-button\").click();"}}' \
  0 ""
# Negative: non-spec file ignored
run_case "css-selector-specs: non-spec ignored" \
  "css-selector-in-specs.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.ts","new_string":"page.locator(\".foo\")"}}' \
  0 ""

echo ""
echo "=== Hook #4: testid-drift-detector ==="
# Smoke: non-svelte file ignored
run_case "testid-drift: non-component silent" \
  "testid-drift-detector.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.txt"}}' \
  0 ""

echo ""
echo "=== Hook #5: legal-text-lastupdated-bump ==="
# Positive: editing privacy_policy.yml without bumping lastUpdated
run_case "legal-bump: edit policy warns if date stale" \
  "legal-text-lastupdated-bump.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/home/superdev/projects/OpenMates/shared/docs/privacy_policy.yml","new_string":"foo"}}' \
  0 "lastUpdated"
# Negative: unrelated file silent
run_case "legal-bump: unrelated file silent" \
  "legal-text-lastupdated-bump.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.yml","new_string":"foo"}}' \
  0 ""

echo ""
echo "=== Hook #6: pii-logger-guard ==="
# Positive: logger.info with email
run_case "pii-logger: logger.info(email) warns" \
  "pii-logger-guard.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.py","new_string":"logger.info(f\"user email: {email}\")"}}' \
  0 "PII"
# Negative: redacted version silent
run_case "pii-logger: hashed email silent" \
  "pii-logger-guard.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.py","new_string":"logger.info(f\"user email: {hash_email(email)}\")"}}' \
  0 ""
# Positive: console.log with token (ts)
run_case "pii-logger: console.log(token) warns" \
  "pii-logger-guard.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.ts","new_string":"console.log(\"got token\", token);"}}' \
  0 "PII"

echo ""
echo "=== Hook #7: cookie-consent-gate ==="
# Positive: new cookie in non-auth path
run_case "cookie-gate: cookie in random route warns" \
  "cookie-consent-gate.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/home/superdev/projects/OpenMates/backend/core/api/app/routes/misc.py","new_string":"response.set_cookie(\"pref\", \"dark\")"}}' \
  0 "cookie"
# Negative: cookie in auth_routes silent
run_case "cookie-gate: cookie in auth_routes silent" \
  "cookie-consent-gate.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/home/superdev/projects/OpenMates/backend/core/api/app/routes/auth_routes/login.py","new_string":"response.set_cookie(\"refresh\", token)"}}' \
  0 ""

echo ""
echo "=== Hook #8: linear-context-auto-prefetch ==="
# Positive: prompt with OPE-42 → reminder injected (fresh session id to avoid sentinel)
run_case "linear-prefetch: OPE-ref reminds" \
  "linear-context-auto-prefetch.sh" \
  '{"prompt":"please fix OPE-42 bug","session_id":"test-'"$RANDOM"'"}' \
  0 "Linear task context"
# Negative: no OPE ref
run_case "linear-prefetch: plain prompt silent" \
  "linear-context-auto-prefetch.sh" \
  '{"prompt":"help me","session_id":"test-xyz"}' \
  0 ""

echo ""
echo "=== Hook #9: svelte5-legacy-syntax ==="
# Positive: $: reactive
run_case "svelte5: \$: warns" \
  "svelte5-legacy-syntax.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.svelte","new_string":"$: doubled = count * 2;"}}' \
  0 "Svelte 4"
# Positive: export let
run_case "svelte5: export let warns" \
  "svelte5-legacy-syntax.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.svelte","new_string":"export let foo: string;"}}' \
  0 "Svelte 4"
# Positive: <slot/>
run_case "svelte5: <slot/> warns" \
  "svelte5-legacy-syntax.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.svelte","new_string":"<div><slot/></div>"}}' \
  0 "Svelte 4"
# Negative: clean Svelte 5
run_case "svelte5: runes silent" \
  "svelte5-legacy-syntax.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.svelte","new_string":"let count = $state(0);\nlet doubled = $derived(count * 2);"}}' \
  0 ""

echo ""
echo "=== Hook #10: auto-rebuild-translations (repaired) ==="
# Smoke: non-yml file ignored
run_case "auto-rebuild: non-yml silent" \
  "auto-rebuild-translations.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.txt"}}' \
  0 ""
# Smoke: non-i18n yml file ignored
run_case "auto-rebuild: random yml silent" \
  "auto-rebuild-translations.sh" \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.yml"}}' \
  0 ""

echo ""
echo "================================"
echo -e "PASS: ${GREEN}$PASS${NC}   FAIL: ${RED}$FAIL${NC}"
if [ "$FAIL" -gt 0 ]; then
  echo -e "${YELLOW}Failures:${NC}"
  for f in "${FAILS[@]}"; do echo "  - $f"; done
  exit 1
fi
