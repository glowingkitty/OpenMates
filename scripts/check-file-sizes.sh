#!/usr/bin/env bash
# check-file-sizes.sh — Report files exceeding 500-line threshold (TEST-05)
#
# Monitors encryption and sync source files for size regressions.
# Grandfathered files (in baseline) are listed but not flagged as new violations.
# Exit code: 0 always (report-only per D-08), but prints WARNING for new violations.
#
# Usage:
#   bash scripts/check-file-sizes.sh              # Full report
#   bash scripts/check-file-sizes.sh --ci         # CI mode: compact output, non-zero if new violations
#   bash scripts/check-file-sizes.sh --update     # Update baseline with current large files

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

THRESHOLD=500
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASELINE_FILE="$SCRIPT_DIR/.file-size-baseline.json"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Monitored directories — strict (encryption/sync) and informational (rest)
STRICT_DIRS=(
  "frontend/packages/ui/src/services/encryption"
  "frontend/packages/ui/src/services/chatSyncService"
  "frontend/packages/ui/src/services"
)
INFO_DIRS=(
  "frontend/apps/web_app/src"
  "backend/core/api/app/routes/handlers"
)

# File extensions to check
FILE_EXTENSIONS=("*.ts" "*.svelte" "*.py")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Read grandfathered files from baseline JSON into an associative array.
# Populates BASELINE_FILES[relative_path]=line_count.
declare -A BASELINE_FILES
load_baseline() {
  if [[ ! -f "$BASELINE_FILE" ]]; then
    return
  fi
  # Parse JSON with lightweight approach (no jq dependency required)
  while IFS= read -r line; do
    # Match lines like:  "path/to/file.ts": 123
    if [[ "$line" =~ \"([^\"]+)\":[[:space:]]*([0-9]+) ]]; then
      local path="${BASH_REMATCH[1]}"
      local count="${BASH_REMATCH[2]}"
      # Skip metadata keys
      if [[ "$path" != "_comment" && "$path" != "threshold" && "$path" != "generated" ]]; then
        BASELINE_FILES["$path"]="$count"
      fi
    fi
  done < "$BASELINE_FILE"
}

# Find all source files in given directories exceeding the threshold.
# Outputs: line_count<TAB>relative_path
find_large_files() {
  local dirs=("$@")
  for dir in "${dirs[@]}"; do
    local abs_dir="$PROJECT_ROOT/$dir"
    if [[ ! -d "$abs_dir" ]]; then
      continue
    fi
    for ext in "${FILE_EXTENSIONS[@]}"; do
      find "$abs_dir" -name "$ext" -type f 2>/dev/null
    done
  done | sort -u | while IFS= read -r filepath; do
    local lines
    lines=$(wc -l < "$filepath")
    if (( lines > THRESHOLD )); then
      local rel_path="${filepath#$PROJECT_ROOT/}"
      printf '%d\t%s\n' "$lines" "$rel_path"
    fi
  done
}

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

mode_update() {
  echo "Updating baseline: $BASELINE_FILE"
  local all_dirs=("${STRICT_DIRS[@]}" "${INFO_DIRS[@]}")
  local tmpfile
  tmpfile=$(mktemp)

  find_large_files "${all_dirs[@]}" | sort -t$'\t' -k2 > "$tmpfile"

  # Build JSON
  {
    printf '{\n'
    printf '  "_comment": "Grandfathered large files as of %s. Files listed here are known to exceed %d lines and are not flagged as new violations.",\n' "$(date +%Y-%m-%d)" "$THRESHOLD"
    printf '  "threshold": %d,\n' "$THRESHOLD"
    printf '  "generated": "%s",\n' "$(date +%Y-%m-%d)"
    printf '  "files": {\n'

    local first=true
    while IFS=$'\t' read -r count path; do
      if [[ "$first" == "true" ]]; then
        first=false
      else
        printf ',\n'
      fi
      printf '    "%s": %d' "$path" "$count"
    done < "$tmpfile"

    if [[ -s "$tmpfile" ]]; then
      printf '\n'
    fi
    printf '  }\n'
    printf '}\n'
  } > "$BASELINE_FILE"

  local total
  total=$(wc -l < "$tmpfile")
  rm -f "$tmpfile"
  echo "Baseline updated: $total files exceeding $THRESHOLD lines"
}

mode_ci() {
  load_baseline
  local all_dirs=("${STRICT_DIRS[@]}" "${INFO_DIRS[@]}")
  local new_violations=0

  while IFS=$'\t' read -r count path; do
    if [[ -z "${BASELINE_FILES[$path]+x}" ]]; then
      echo "NEW VIOLATION: $path ($count lines)"
      new_violations=$((new_violations + 1))
    fi
  done < <(find_large_files "${all_dirs[@]}")

  if (( new_violations > 0 )); then
    echo "$new_violations new file(s) exceed $THRESHOLD lines"
    exit 1
  else
    echo "No new violations (threshold: $THRESHOLD lines)"
    exit 0
  fi
}

mode_report() {
  load_baseline
  local all_dirs=("${STRICT_DIRS[@]}" "${INFO_DIRS[@]}")
  local total_checked=0
  local known_count=0
  local new_count=0

  echo "=== File Size Report (threshold: $THRESHOLD lines) ==="
  echo ""

  # Count total files checked
  for dir in "${all_dirs[@]}"; do
    local abs_dir="$PROJECT_ROOT/$dir"
    if [[ ! -d "$abs_dir" ]]; then
      continue
    fi
    for ext in "${FILE_EXTENSIONS[@]}"; do
      local c
      c=$(find "$abs_dir" -name "$ext" -type f 2>/dev/null | wc -l)
      total_checked=$((total_checked + c))
    done
  done

  echo "Files checked: ~$total_checked"
  echo ""

  # Report large files
  local has_output=false
  while IFS=$'\t' read -r count path; do
    has_output=true
    if [[ -n "${BASELINE_FILES[$path]+x}" ]]; then
      echo "  KNOWN:         $path ($count lines)"
      known_count=$((known_count + 1))
    else
      echo "  NEW VIOLATION: $path ($count lines)"
      new_count=$((new_count + 1))
    fi
  done < <(find_large_files "${all_dirs[@]}" | sort -t$'\t' -k2)

  if [[ "$has_output" == "false" ]]; then
    echo "  No files exceed $THRESHOLD lines."
  fi

  echo ""
  echo "--- Summary ---"
  echo "Known large files (grandfathered): $known_count"
  echo "New violations: $new_count"

  if (( new_count > 0 )); then
    echo ""
    echo "WARNING: $new_count new file(s) exceed the $THRESHOLD-line threshold."
    echo "Consider splitting or add to baseline with: bash scripts/check-file-sizes.sh --update"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
  --update)
    mode_update
    ;;
  --ci)
    mode_ci
    ;;
  *)
    mode_report
    ;;
esac
