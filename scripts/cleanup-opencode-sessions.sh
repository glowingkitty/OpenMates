#!/bin/bash
# OpenCode Session Cleanup Script
# Deletes opencode sessions older than 7 days that do NOT have "TODO" (case-insensitive)
# in their title. Sessions with TODO are kept indefinitely until manually addressed.
#
# Runs daily via crontab at 01:30 UTC.
# Logs to: logs/opencode-cleanup.log
#
# Architecture: directly queries opencode's SQLite DB at the standard XDG data path,
# then calls `opencode session delete` per session to ensure all associated storage
# files (storage/session_diff/) are cleaned up alongside DB rows.

set -euo pipefail

DB_PATH="$HOME/.local/share/opencode/opencode.db"
OPENCODE_BIN="$HOME/.npm-global/bin/opencode"
CUTOFF_MS=$(python3 -c "import time; print(int((time.time() - 7*24*3600) * 1000))")

echo "=========================================="
echo "OpenCode Session Cleanup"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="
echo ""
echo "Cutoff: sessions not updated since $(date -u -d "@$(( CUTOFF_MS / 1000 ))" '+%Y-%m-%d %H:%M UTC')"
echo "Rule: delete if older than 7 days AND title does NOT contain 'TODO' (case-insensitive)"
echo ""

# Verify DB exists
if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: opencode DB not found at $DB_PATH — aborting."
    exit 1
fi

# Verify opencode binary exists
if [ ! -x "$OPENCODE_BIN" ]; then
    OPENCODE_BIN=$(command -v opencode 2>/dev/null || echo "")
    if [ -z "$OPENCODE_BIN" ]; then
        echo "ERROR: opencode binary not found — aborting."
        exit 1
    fi
fi

# Print candidates summary and collect IDs
CANDIDATES_FILE=$(mktemp)
python3 - > "$CANDIDATES_FILE" <<PYEOF
import sqlite3
from datetime import datetime, timezone

conn = sqlite3.connect("$DB_PATH")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
    SELECT id, title, time_updated
    FROM session
    WHERE time_archived IS NULL
      AND time_updated < $CUTOFF_MS
      AND UPPER(title) NOT LIKE '%TODO%'
    ORDER BY time_updated ASC
""")
rows = cur.fetchall()
conn.close()

print(f"{'Session ID':<35} {'Updated':<12} {'Title'}")
print("-" * 100)
for r in rows:
    updated = datetime.fromtimestamp(r['time_updated'] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    title = r['title'][:55] + "..." if len(r['title']) > 55 else r['title']
    print(f"{r['id']:<35} {updated:<12} {title}")
PYEOF

TOTAL=$(grep -c "^ses_" "$CANDIDATES_FILE" 2>/dev/null || echo "0")

if [ "$TOTAL" -eq 0 ]; then
    echo "No sessions to delete — nothing to do."
    rm -f "$CANDIDATES_FILE"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHONPATH="$SCRIPT_DIR" python3 -c "
from _nightly_report import write_nightly_report
write_nightly_report(
    job='session-cleanup',
    status='ok',
    summary='No sessions to delete — all recent or have TODO.',
)
"
    echo ""
    echo "Done."
    exit 0
fi

echo "Found $TOTAL session(s) to delete:"
echo ""
cat "$CANDIDATES_FILE"
echo ""
echo "Deleting..."
echo ""

DELETED=0
FAILED=0

while IFS= read -r LINE; do
    SESSION_ID=$(echo "$LINE" | awk '{print $1}')
    [[ "$SESSION_ID" =~ ^ses_ ]] || continue
    if "$OPENCODE_BIN" session delete "$SESSION_ID" 2>/dev/null; then
        echo "  OK  $SESSION_ID"
        DELETED=$(( DELETED + 1 ))
    else
        echo "  ERR $SESSION_ID"
        FAILED=$(( FAILED + 1 ))
    fi
done < "$CANDIDATES_FILE"

rm -f "$CANDIDATES_FILE"

echo ""
echo "=========================================="
echo "Summary: $DELETED deleted, $FAILED failed (of $TOTAL candidates)"
DB_SIZE=$(du -sh "$DB_PATH" | cut -f1)
echo "DB size now: $DB_SIZE"
echo "=========================================="
echo ""

# Write nightly report for daily meeting consumption
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$SCRIPT_DIR" python3 -c "
from _nightly_report import write_nightly_report
write_nightly_report(
    job='session-cleanup',
    status='ok' if ${FAILED} == 0 else 'warning',
    summary='Session cleanup: ${DELETED} deleted, ${FAILED} failed (of ${TOTAL} candidates). DB size: ${DB_SIZE}.',
    details={
        'deleted': ${DELETED},
        'failed': ${FAILED},
        'total_candidates': ${TOTAL},
        'db_size': '${DB_SIZE}',
    },
)
"
