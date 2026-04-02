#!/bin/bash
# scripts/check_embed_fullscreen_coverage.sh
#
# Validates that every embed type registered in embedRegistry.generated.ts with a
# fullscreen component has a corresponding routing branch in ActiveChat.svelte.
#
# Run manually or integrate into deploy pipeline.
# Exit code: 0 = all covered, 1 = missing branches found.

set -euo pipefail

REGISTRY="frontend/packages/ui/src/data/embedRegistry.generated.ts"
ACTIVE_CHAT="frontend/packages/ui/src/components/ActiveChat.svelte"

if [[ ! -f "$REGISTRY" ]] || [[ ! -f "$ACTIVE_CHAT" ]]; then
    echo "ERROR: Required files not found. Run from project root."
    exit 1
fi

MISSING=()

# Extract all keys from the EMBED_FULLSCREEN_COMPONENTS block
KEYS=$(awk '/EMBED_FULLSCREEN_COMPONENTS/,/^}/' "$REGISTRY" | \
       grep -oP '^\s*"\K[^"]+(?=":)')

for key in $KEYS; do
    case "$key" in
        app:*)
            # App-skill-use type: "app:appId:skillId" → check for appId === 'X' && skillId === 'Y'
            app_id=$(echo "$key" | cut -d: -f2)
            skill_id=$(echo "$key" | cut -d: -f3)
            # Check for the appId + skillId pattern in ActiveChat (also handles || combined branches)
            if ! grep -qP "appId\s*===\s*'${app_id}'\s*&&\s*(skillId\s*===\s*'${skill_id}'|\(skillId\s*===\s*'[^']*'\s*\|\|\s*skillId\s*===\s*'${skill_id}')" "$ACTIVE_CHAT" && \
               ! grep -qP "appId\s*===\s*'${app_id}'\s*&&\s*\(skillId\s*===\s*'${skill_id}'" "$ACTIVE_CHAT"; then
                MISSING+=("$key (app-skill-use: appId='$app_id' + skillId='$skill_id')")
            fi
            ;;
        image)
            # 'image' is intentionally excluded — it's a content sub-type, not a top-level embed
            ;;
        web-website)
            # 'web-website' is routed as embedType === 'website' (frontend normalizes the name)
            if ! grep -qP "embedType\s*===\s*'website'" "$ACTIVE_CHAT"; then
                MISSING+=("$key (direct embedType, routed as 'website')")
            fi
            ;;
        *)
            # Direct embed type: check for embedType === 'X'
            if ! grep -qP "embedType\s*===\s*'${key}'" "$ACTIVE_CHAT"; then
                MISSING+=("$key (direct embedType)")
            fi
            ;;
    esac
done

if [[ ${#MISSING[@]} -eq 0 ]]; then
    echo "✓ All embed fullscreen types have routing branches in ActiveChat.svelte"
    exit 0
else
    echo "✗ Missing embed fullscreen routing branches in ActiveChat.svelte:"
    echo ""
    for m in "${MISSING[@]}"; do
        echo "  - $m"
    done
    echo ""
    echo "Add a {:else if} branch for each missing type in ActiveChat.svelte's fullscreen routing block."
    exit 1
fi
