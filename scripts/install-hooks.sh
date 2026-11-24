#!/usr/bin/env bash
# install-hooks.sh — Install git hooks for this repository.
#
# Run once after cloning:
#   ./scripts/install-hooks.sh
#
# Hooks installed:
#   pre-commit: runs staged maintainability checks and translation validation
#               when frontend files are staged.
#   commit-msg: checks public text and staged names (scripts/public_link_guard.py).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir)/hooks"
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
# Blocks high-confidence technical debt and missing $text() translation keys.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "[pre-commit] Running staged code-quality guard..."
python3 "$REPO_ROOT/scripts/code_quality_guard.py"

# Only run when frontend files are staged (avoid slow npm check for backend-only commits)
if ! git diff --cached --name-only | grep -q "^frontend/"; then
    exit 0
fi

UI_DIR="$REPO_ROOT/frontend/packages/ui"

if [ ! -f "$UI_DIR/package.json" ]; then
    echo "Warning: frontend/packages/ui/package.json not found — skipping translation validation"
    exit 0
fi

echo '🔍 [pre-commit] Checking $text() translation keys...'

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

# ── commit-msg: no chat or session links in public commit messages (owner, 23 Nov) ──
COMMIT_MSG="$HOOKS_DIR/commit-msg"
cat > "$COMMIT_MSG" << 'HOOK'
#!/usr/bin/env bash
# commit-msg hook — installed by scripts/install-hooks.sh
# Check the actual stored message, including lines beginning with a comment character.
set -e
guard="$(git rev-parse --show-toplevel)/scripts/public_link_guard.py"
[ -f "$guard" ] || guard="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/scripts/public_link_guard.py"
[ -f "$guard" ] || exit 0
python3 "$guard" commit-msg "$1"
if branch=$(git symbolic-ref --quiet HEAD); then
    python3 "$guard" branch "$branch"
fi
exec python3 "$guard" tree
HOOK
chmod +x "$COMMIT_MSG"
echo "✅ Installed: $COMMIT_MSG"

echo ""
echo "The pre-commit hook will now block high-confidence debt and missing \$text() keys."

PRE_PUSH="$HOOKS_DIR/pre-push"
cat > "$PRE_PUSH" << 'HOOK'
#!/usr/bin/env bash
set -euo pipefail
guard="$(git rev-parse --show-toplevel)/scripts/public_link_guard.py"
[ -f "$guard" ] || guard="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/scripts/public_link_guard.py"
exec python3 "$guard" pre-push "$1"
HOOK
chmod +x "$PRE_PUSH"
echo "Installed: $PRE_PUSH"
