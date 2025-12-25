#!/usr/bin/env bash
# Script to find all files with more than 500 lines of code in the repository
# Prints each file with its line count, sorted by line count (descending)

set -euo pipefail

# Get repository root
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "${repo_root}"

# Minimum line count threshold
MIN_LINES="${1:-500}"

# Check if MIN_LINES is a valid number
if ! [[ "${MIN_LINES}" =~ ^[0-9]+$ ]]; then
  echo "Error: Line count must be a positive integer" >&2
  echo "Usage: $0 [MIN_LINES]" >&2
  echo "Example: $0 500" >&2
  exit 1
fi

echo "Finding files with more than ${MIN_LINES} lines..."
echo ""

# Arrays to store results: "line_count|file_path"
declare -a i18n_yml_results=()
declare -a other_results=()

# Find all code files (excluding common directories and non-code files)
while IFS= read -r -d '' file; do
  # Skip binary files and common non-code directories
  if [[ -f "${file}" ]]; then
    # Skip log files, binary files, and other non-code files
    case "${file}" in
      *.log|*.log.*|*.pdf|*.jpg|*.jpeg|*.png|*.gif|*.ico|*.svg|*.woff|*.woff2|*.ttf|*.eot|*.mp4|*.mp3|*.zip|*.tar|*.gz|*.bz2|*.xz|*.7z|*.rar)
        continue
        ;;
      */logs/*|*/log/*)
        continue
        ;;
    esac
    
    # Skip JSON files from locales folder
    if [[ "${file}" =~ /locales/.*\.json$ ]]; then
      continue
    fi
    
    # Skip Jupyter notebook files
    if [[ "${file}" =~ \.ipynb$ ]]; then
      continue
    fi
    
    # Count lines in the file
    line_count=$(wc -l < "${file}" 2>/dev/null || echo "0")
    
    # Check if line count exceeds threshold
    if [[ "${line_count}" -gt "${MIN_LINES}" ]]; then
      # Categorize: YAML files in i18n folder vs everything else
      if [[ "${file}" =~ /i18n/.*\.yml$ ]] || [[ "${file}" =~ /i18n/.*\.yaml$ ]]; then
        i18n_yml_results+=("${line_count}|${file}")
      else
        other_results+=("${line_count}|${file}")
      fi
    fi
  fi
done < <(find . -type f \
  ! -path "*/\.*" \
  ! -path "*/node_modules/*" \
  ! -path "*/__pycache__/*" \
  ! -path "*/\.git/*" \
  ! -path "*/dist/*" \
  ! -path "*/build/*" \
  ! -path "*/target/*" \
  ! -path "*/\.next/*" \
  ! -path "*/\.turbo/*" \
  ! -path "*/coverage/*" \
  ! -path "*/\.venv/*" \
  ! -path "*/venv/*" \
  ! -path "*/tree-sitter-env/*" \
  ! -path "*/pnpm-lock.yaml" \
  ! -path "*/package-lock.json" \
  ! -path "*/yarn.lock" \
  ! -path "*/\.DS_Store" \
  -print0 2>/dev/null)

# Sort results by line count (descending)
IFS=$'\n' sorted_i18n_yml=($(printf '%s\n' "${i18n_yml_results[@]}" | sort -t'|' -k1 -rn))
IFS=$'\n' sorted_other=($(printf '%s\n' "${other_results[@]}" | sort -t'|' -k1 -rn))

# Print i18n YAML files
if [[ ${#sorted_i18n_yml[@]} -gt 0 ]]; then
  echo "=== i18n YAML Files (${#sorted_i18n_yml[@]} file(s)) ==="
  echo ""
  printf "%-10s %s\n" "LINES" "FILE PATH"
  echo "----------------------------------------"
  
  for result in "${sorted_i18n_yml[@]}"; do
    line_count="${result%%|*}"
    file_path="${result#*|}"
    # Remove leading ./ from path for cleaner output
    file_path="${file_path#./}"
    printf "%-10s %s\n" "${line_count}" "${file_path}"
  done
  echo ""
fi

# Print other files
if [[ ${#sorted_other[@]} -gt 0 ]]; then
  echo "=== Other Files (${#sorted_other[@]} file(s)) ==="
  echo ""
  printf "%-10s %s\n" "LINES" "FILE PATH"
  echo "----------------------------------------"
  
  for result in "${sorted_other[@]}"; do
    line_count="${result%%|*}"
    file_path="${result#*|}"
    # Remove leading ./ from path for cleaner output
    file_path="${file_path#./}"
    printf "%-10s %s\n" "${line_count}" "${file_path}"
  done
  echo ""
fi

# Summary
total_files=$((${#sorted_i18n_yml[@]} + ${#sorted_other[@]}))
if [[ ${total_files} -eq 0 ]]; then
  echo "No files found with more than ${MIN_LINES} lines."
else
  echo "Total: ${total_files} file(s) with more than ${MIN_LINES} lines"
  echo "  - i18n YAML files: ${#sorted_i18n_yml[@]}"
  echo "  - Other files: ${#sorted_other[@]}"
fi

