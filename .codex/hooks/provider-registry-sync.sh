#!/bin/bash
# Hook: PreToolUse (Edit|Write) — provider-registry-sync
# ------------------------------------------------------------------
# GDPR enforcement: when a new third-party provider is introduced in
# code, verify that provider is disclosed in shared/docs/privacy_policy.yml.
#
# Triggers on:
#   - Writes under backend/shared/providers/<new_dir>/
#   - Edits that add a new SDK import (openai, anthropic, stripe, brave,
#     firecrawl, groq, together, mistral, recraft, fal, sightengine,
#     meetup, luma, discord, cerebras, serpapi, google-maps, googlemaps)
#
# Strictness: WARN ONLY (exit 0 + stderr + additionalContext). Flip to
# exit 2 once the regex is proven accurate.
#
# Related: OPE-375, .claude/rules/privacy.md, shared/docs/privacy_policy.yml

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only inspect Python files and package manifests
case "$FILE" in
  *.py|*/package.json|*/pyproject.toml|*/requirements*.txt) ;;
  *) exit 0 ;;
esac

PROJECT_DIR="/home/superdev/projects/OpenMates"
POLICY="$PROJECT_DIR/shared/docs/privacy_policy.yml"
[ -f "$POLICY" ] || exit 0

# Extract the candidate new content depending on the tool
if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

# Providers we care about (SDK names / import tokens → canonical policy key)
# Format: "sdk_pattern:policy_key"
PROVIDERS_MAP=(
  "openai:openai"
  "anthropic:anthropic"
  "stripe:stripe"
  "brave[_-]search:brave"
  "firecrawl:firecrawl"
  "groq:groq"
  "together:together"
  "mistralai:mistral"
  "recraft:recraft"
  "fal[_-]client:fal"
  "sightengine:sightengine"
  "meetup:meetup"
  "luma:luma"
  "discord:discord"
  "cerebras:cerebras"
  "serpapi:serpapi"
  "googlemaps:google_maps"
  "google[_.-]maps:google_maps"
  "posthog:posthog"
  "mixpanel:mixpanel"
)

# Extract all lowercase keys under any `providers:` block in the policy.
# Provider entries look like:
#   providers:
#     vercel:
#     hetzner:
POLICY_PROVIDERS=$(awk '
  /^\s*providers:\s*$/ { in_block=1; next }
  in_block && /^[a-z]/ { in_block=0 }
  in_block && /^\s+[a-z][a-z0-9_]*:/ {
    gsub(/^\s+/, "");
    gsub(/:.*$/, "");
    print
  }
' "$POLICY" | sort -u)

WARNINGS=()
for entry in "${PROVIDERS_MAP[@]}"; do
  sdk="${entry%%:*}"
  key="${entry##*:}"
  # Match new content lines that are added imports or from-imports
  if echo "$NEW_CONTENT" | grep -qiE "^\s*(from|import)\s+${sdk}\b|[\"']${sdk}[\"']"; then
    if ! echo "$POLICY_PROVIDERS" | grep -qx "$key"; then
      WARNINGS+=("$key (matched pattern: $sdk)")
    fi
  fi
done

# Also flag brand-new provider directories
if [[ "$FILE" == *"backend/shared/providers/"* ]]; then
  NEW_DIR=$(echo "$FILE" | sed -n 's|.*backend/shared/providers/\([^/]*\)/.*|\1|p')
  if [ -n "$NEW_DIR" ] && [ ! -d "$PROJECT_DIR/backend/shared/providers/$NEW_DIR" ]; then
    if ! echo "$POLICY_PROVIDERS" | grep -qx "$NEW_DIR"; then
      WARNINGS+=("$NEW_DIR (new provider directory)")
    fi
  fi
fi

if [ ${#WARNINGS[@]} -gt 0 ]; then
  MSG="⚠️  GDPR/privacy-policy-sync: provider(s) not disclosed in shared/docs/privacy_policy.yml — $(IFS=,; echo "${WARNINGS[*]}"). Add an entry under the appropriate provider_group (A-J) and update frontend/packages/ui/src/i18n/sources/legal/privacy.yml + bump lastUpdated in privacy-policy.ts before deploying. (warn-only, see .claude/rules/privacy.md)"
  echo "$MSG" >&2
  # Also return via additionalContext so Claude sees it inline
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
