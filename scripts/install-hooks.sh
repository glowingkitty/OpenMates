#!/usr/bin/env bash
# install-hooks.sh — Install git hooks for this repository.
#
# Run once after cloning:
#   ./scripts/install-hooks.sh
#
# Hooks installed:
#   pre-commit: runs translation validation when frontend files are staged,
#               blocking commits that would break the Vercel build.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
SCRIPTS_DIR="$REPO_ROOT/scripts"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "Error: .git/hooks directory not found. Run this script from the repo root." >&2
    exit 1
fi

# ── pre-commit ───────────────────────────────────────────────────────────────
PRE_COMMIT="$HOOKS_DIR/pre-commit"

cat > "$PRE_COMMIT" << 'HOOK'
#!/usr/bin/env bash
# pre-commit hook — installed by scripts/install-hooks.sh
# Blocks commits that reference missing $text() translation keys.

set -euo pipefail

# Only run when frontend files are staged (avoid slow npm check for backend-only commits)
if ! git diff --cached --name-only | grep -q "^frontend/"; then
    exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
UI_DIR="$REPO_ROOT/frontend/packages/ui"

if [ ! -f "$UI_DIR/package.json" ]; then
    echo "Warning: frontend/packages/ui/package.json not found — skipping translation validation"
    exit 0
fi

echo "🔍 [pre-commit] Checking $text() translation keys..."

# Run validate:locales and capture output
OUTPUT="$(cd "$UI_DIR" && npm run validate:locales 2>&1)"
EXIT_CODE=$?

# Only hard-fail on Step 4 errors (missing $text() keys in en.json).
# Step 6 cross-locale warnings are pre-existing and don't block commits.
if echo "$OUTPUT" | grep -q "not found in en.json"; then
    echo ""
    echo "❌ [pre-commit] TRANSLATION ERROR — commit blocked"
    echo ""
    echo "$OUTPUT" | grep -E "not found in en.json|\\\$text\(|❌ Found"
    echo ""
    echo "Fix: add the missing key to frontend/packages/ui/src/i18n/sources/"
    echo "Then run: cd frontend/packages/ui && npm run build:translations"
    echo ""
    exit 1
fi

echo "✅ [pre-commit] Translations OK"
HOOK

chmod +x "$PRE_COMMIT"
echo "✅ Installed: $PRE_COMMIT"
echo ""
echo "The pre-commit hook will now block commits with missing \$text() keys."
echo "To skip in an emergency (not recommended): git commit --no-verify"
