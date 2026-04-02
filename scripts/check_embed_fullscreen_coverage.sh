#!/bin/bash
# scripts/check_embed_fullscreen_coverage.sh
#
# Validates that every embed type registered in embedRegistry.generated.ts with a
# fullscreen component has a corresponding routing branch in ActiveChat.svelte,
# AND that search embeds with children pass initialChildEmbedId.
#
# Run manually or integrate into deploy pipeline.
# Exit code: 0 = all covered, 1 = missing branches found.

set -euo pipefail

REGISTRY="frontend/packages/ui/src/data/embedRegistry.generated.ts"
ACTIVE_CHAT="frontend/packages/ui/src/components/ActiveChat.svelte"
EMBEDS_DIR="frontend/packages/ui/src/components/embeds"

if [[ ! -f "$REGISTRY" ]] || [[ ! -f "$ACTIVE_CHAT" ]]; then
    echo "ERROR: Required files not found. Run from project root."
    exit 1
fi

ERRORS=()

# --- Check 1: All registered embed types have routing branches ---

KEYS=$(awk '/EMBED_FULLSCREEN_COMPONENTS/,/^}/' "$REGISTRY" | \
       grep -oP '^\s*"\K[^"]+(?=":)')

for key in $KEYS; do
    case "$key" in
        app:*)
            app_id=$(echo "$key" | cut -d: -f2)
            skill_id=$(echo "$key" | cut -d: -f3)
            if ! grep -qP "appId\s*===\s*'${app_id}'\s*&&\s*(skillId\s*===\s*'${skill_id}'|\(skillId\s*===\s*'[^']*'\s*\|\|\s*skillId\s*===\s*'${skill_id}')" "$ACTIVE_CHAT" && \
               ! grep -qP "appId\s*===\s*'${app_id}'\s*&&\s*\(skillId\s*===\s*'${skill_id}'" "$ACTIVE_CHAT"; then
                ERRORS+=("[routing] $key — no ActiveChat branch for appId='$app_id' + skillId='$skill_id'")
            fi
            ;;
        image)
            # Intentionally excluded — content sub-type, not top-level embed
            ;;
        web-website)
            if ! grep -qP "embedType\s*===\s*'website'" "$ACTIVE_CHAT"; then
                ERRORS+=("[routing] $key — no ActiveChat branch (routed as 'website')")
            fi
            ;;
        *)
            if ! grep -qP "embedType\s*===\s*'${key}'" "$ACTIVE_CHAT"; then
                ERRORS+=("[routing] $key — no ActiveChat branch for embedType='$key'")
            fi
            ;;
    esac
done

# --- Check 2: Search embeds using SearchResultsTemplate pass initialChildEmbedId ---

# Find all *Fullscreen.svelte files that import SearchResultsTemplate (not just comments)
SEARCH_FULLSCREENS=$(grep -rl "import SearchResultsTemplate" "$EMBEDS_DIR" --include="*Fullscreen.svelte" 2>/dev/null || true)

for f in $SEARCH_FULLSCREENS; do
    basename=$(basename "$f")
    # Check the component accepts initialChildEmbedId
    if ! grep -q "initialChildEmbedId" "$f"; then
        ERRORS+=("[initialChildEmbedId] $basename — uses SearchResultsTemplate but missing initialChildEmbedId prop")
    fi
done

# --- Report ---

if [[ ${#ERRORS[@]} -eq 0 ]]; then
    echo "✓ All embed fullscreen types have routing branches and initialChildEmbedId passthrough"
    exit 0
else
    echo "✗ Embed fullscreen coverage issues:"
    echo ""
    for e in "${ERRORS[@]}"; do
        echo "  - $e"
    done
    echo ""
    echo "Fix all issues above to ensure embed fullscreens work correctly."
    exit 1
fi
