#!/bin/bash
# Hook: PreToolUse (Edit|Write) — privacy-promise-guard
# ------------------------------------------------------------------
# When an agent touches a file listed in the enforcement section of any
# entry in shared/docs/privacy_promises.yml, surface the affected promise
# id(s), their user-facing headings, and the linked test(s). Escalates
# with a "LINKED TEST REMOVED" warning if any linked test file no longer
# exists on disk — that's the most common way a regression sneaks in.
#
# Strictness: WARN ONLY (exit 0). Never blocks.
# Related: shared/docs/privacy_promises.yml, backend/tests/test_privacy_promises.py
#          docs (plan): /home/superdev/.claude/plans/fuzzy-sauteeing-pancake.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO_ROOT" ] && exit 0

REGISTRY="$REPO_ROOT/shared/docs/privacy_promises.yml"
[ -f "$REGISTRY" ] || exit 0

# Normalize FILE to a repo-relative path for comparison.
case "$FILE" in
  "$REPO_ROOT"/*) REL="${FILE#$REPO_ROOT/}" ;;
  /*) exit 0 ;;  # absolute path outside repo — ignore
  *) REL="$FILE" ;;
esac

# Delegate matching to python3 (PyYAML is available on the project's api image
# and on dev hosts; fall back silently if not).
OUTPUT=$(REPO_ROOT="$REPO_ROOT" REL="$REL" python3 - <<'PY' 2>/dev/null
import os, sys, yaml
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
rel = os.environ["REL"]
registry_path = repo / "shared" / "docs" / "privacy_promises.yml"

try:
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

hits = []
for p in data.get("promises", []):
    for e in p.get("enforcement", []):
        if e.get("file") == rel:
            tests = p.get("tests", [])
            missing = [t["path"] for t in tests if not (repo / t["path"]).exists()]
            hits.append({
                "id": p["id"],
                "severity": p.get("severity", "?"),
                "what": e.get("what", ""),
                "tests": [t["path"] for t in tests],
                "missing_tests": missing,
            })
            break

if not hits:
    sys.exit(0)

lines = []
for h in hits:
    lines.append(f"  • [{h['severity']}] {h['id']} — {h['what']}")
    if h["tests"]:
        lines.append(f"      tests: {', '.join(h['tests'])}")
    if h["missing_tests"]:
        lines.append(f"      🚨 LINKED TEST REMOVED: {', '.join(h['missing_tests'])}")

print(f"🛡  privacy-promise-guard: this file enforces {len(hits)} public privacy promise(s).")
print("\n".join(lines))
print("  If you change its behaviour, re-run the linked test(s) and update shared/docs/privacy_promises.yml.")
PY
)

if [ -n "$OUTPUT" ]; then
  echo "$OUTPUT" >&2
  jq -nc --arg msg "$OUTPUT" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
