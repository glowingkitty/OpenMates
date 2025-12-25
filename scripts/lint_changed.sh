#!/usr/bin/env bash
set -euo pipefail

# Parse command-line arguments
full_repo_mode=false
check_py=false
check_ts=false
check_svelte=false
check_css=false
check_html=false
check_yml=false

# Parse arguments
for arg in "$@"; do
  case "${arg}" in
    full_repo)
      full_repo_mode=true
      ;;
    --py)
      check_py=true
      ;;
    --ts)
      check_ts=true
      ;;
    --svelte)
      check_svelte=true
      ;;
    --css)
      check_css=true
      ;;
    --html)
      check_html=true
      ;;
    --yml)
      check_yml=true
      ;;
    --help|-h)
      echo "Usage: $0 [full_repo] [--py] [--ts] [--svelte] [--css] [--html] [--yml]"
      echo ""
      echo "Options:"
      echo "  full_repo    Check all files in the repository (default: only uncommitted changes)"
      echo "  --py         Only check Python (.py) files"
      echo "  --ts         Only check TypeScript (.ts, .tsx) files"
      echo "  --svelte     Only check Svelte (.svelte) files"
      echo "  --css        Only check CSS (.css) files"
      echo "  --html       Only check HTML (.html) files"
      echo "  --yml        Only check YAML (.yml, .yaml) files"
      echo ""
      echo "Examples:"
      echo "  $0                    # Check uncommitted changes, all file types"
      echo "  $0 full_repo          # Check all files, all file types"
      echo "  $0 --py               # Check uncommitted .py files only"
      echo "  $0 full_repo --py     # Check all .py files"
      echo "  $0 --ts --svelte      # Check uncommitted .ts and .svelte files"
      echo "  $0 --yml              # Check uncommitted .yml and .yaml files"
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Use --help for usage information" >&2
      exit 1
      ;;
  esac
done

# If no file type filters are specified, check all types
if ! ${check_py} && ! ${check_ts} && ! ${check_svelte} && ! ${check_css} && ! ${check_html} && ! ${check_yml}; then
  check_py=true
  check_ts=true
  check_svelte=true
  check_css=true
  check_html=true
  check_yml=true
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  echo "error: must be run inside a git repo" >&2
  exit 2
fi

cd "${repo_root}"

python_cmd="${PYTHON:-}"
if [[ -z "${python_cmd}" ]]; then
  if [[ -n "${VIRTUAL_ENV-}" ]] && command -v python >/dev/null 2>&1; then
    python_cmd="python"
  elif command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  fi
fi
if [[ -n "${python_cmd}" ]] && ! command -v "${python_cmd}" >/dev/null 2>&1; then
  echo "Python: interpreter not found at '${python_cmd}' (set PYTHON=/path/to/python); skipping." >&2
  python_cmd=""
fi

overall_status=0

# Collect files based on mode
if ${full_repo_mode}; then
  # Get all tracked files in the repository
  mapfile -d '' changed_files < <(
    git ls-files -z
  )
else
  # Get only uncommitted changes (default behavior)
  mapfile -d '' changed_files < <(
    {
      git diff --name-only -z --diff-filter=ACMRTUXB
      git diff --name-only -z --cached --diff-filter=ACMRTUXB
      git ls-files -z --others --exclude-standard
    } | awk 'BEGIN{RS="\0"; ORS="\0"} !seen[$0]++ {print}'
  )
fi

if (( ${#changed_files[@]} == 0 )); then
  if ${full_repo_mode}; then
    echo "No files found in repository."
  else
    echo "No uncommitted file changes."
  fi
  exit 0
fi

declare -a py_files=()
declare -a ts_files=()
declare -a svelte_files=()
declare -a css_files=()
declare -a html_files=()
declare -a yml_files=()

# Separate files by type based on enabled checks
for path in "${changed_files[@]}"; do
  [[ -f "${path}" ]] || continue
  case "${path}" in
    *.py)
      if ${check_py}; then
        py_files+=("${path}")
      fi
      ;;
    *.ts|*.tsx)
      if ${check_ts}; then
        ts_files+=("${path}")
      fi
      ;;
    *.svelte)
      if ${check_svelte}; then
        svelte_files+=("${path}")
      fi
      ;;
    *.css)
      if ${check_css}; then
        css_files+=("${path}")
      fi
      ;;
    *.html)
      if ${check_html}; then
        html_files+=("${path}")
      fi
      ;;
    *.yml|*.yaml)
      if ${check_yml}; then
        yml_files+=("${path}")
      fi
      ;;
  esac
done

# Combine for ESLint (which handles TS, Svelte, CSS, and HTML)
# Note: ESLint can lint TypeScript, Svelte, CSS, and HTML files
declare -a js_files=()
${check_ts} && js_files+=("${ts_files[@]}")
${check_svelte} && js_files+=("${svelte_files[@]}")
${check_css} && js_files+=("${css_files[@]}")
${check_html} && js_files+=("${html_files[@]}")

run_python_lint() {
  if (( ${#py_files[@]} == 0 )); then
    return 0
  fi

  if [[ -z "${python_cmd}" ]]; then
    echo "Python: no interpreter configured; skipping." >&2
    return 0
  fi

  local python_mode=""
  if "${python_cmd}" -m ruff --version >/dev/null 2>&1; then
    python_mode="ruff_module"
  elif command -v ruff >/dev/null 2>&1; then
    python_mode="ruff_bin"
  elif "${python_cmd}" -c "import flake8" >/dev/null 2>&1; then
    python_mode="flake8"
  elif "${python_cmd}" -c "import pylint" >/dev/null 2>&1; then
    python_mode="pylint"
  else
    python_mode="compile"
    echo "Python: no supported linter found (tried: ruff/flake8/pylint); running syntax check instead." >&2
  fi

  local file
  for file in "${py_files[@]}"; do
    case "${python_mode}" in
      ruff_module)
        if "${python_cmd}" -m ruff check "${file}"; then
          echo "Python: ok ${file}"
        else
          echo "Python: error ${file}" >&2
          overall_status=1
        fi
        ;;
      ruff_bin)
        if ruff check "${file}"; then
          echo "Python: ok ${file}"
        else
          echo "Python: error ${file}" >&2
          overall_status=1
        fi
        ;;
      flake8)
        if "${python_cmd}" -m flake8 "${file}"; then
          echo "Python: ok ${file}"
        else
          echo "Python: error ${file}" >&2
          overall_status=1
        fi
        ;;
      pylint)
        if "${python_cmd}" -m pylint "${file}"; then
          echo "Python: ok ${file}"
        else
          echo "Python: error ${file}" >&2
          overall_status=1
        fi
        ;;
      compile)
        if "${python_cmd}" -m py_compile "${file}"; then
          echo "Python: ok ${file}"
        else
          echo "Python: error ${file}" >&2
          overall_status=1
        fi
        ;;
    esac
  done
}

find_pkg_root() {
  local start_dir="$1"
  local dir="$start_dir"
  while [[ "${dir}" != "${repo_root}" && "${dir}" != "/" ]]; do
    if [[ -f "${dir}/package.json" ]]; then
      printf '%s\n' "${dir}"
      return 0
    fi
    dir="$(dirname "${dir}")"
  done
  if [[ -f "${repo_root}/package.json" ]]; then
    printf '%s\n' "${repo_root}"
    return 0
  fi
  return 1
}

run_eslint_file() {
  local pnpm_cmd="$1"
  local pkg_root="$2"
  local rel_file="$3"
  local label="$4"

  if [[ "${pnpm_cmd}" == "pnpm" ]]; then
    if pnpm -C "${pkg_root}" exec eslint --max-warnings=0 --no-ignore "${rel_file}"; then
      echo "${label}: ok ${pkg_root#${repo_root}/}/${rel_file}"
    else
      echo "${label}: error ${pkg_root#${repo_root}/}/${rel_file}" >&2
      overall_status=1
    fi
  else
    if npm --prefix "${pkg_root}" exec -- eslint --max-warnings=0 --no-ignore "${rel_file}"; then
      echo "${label}: ok ${pkg_root#${repo_root}/}/${rel_file}"
    else
      echo "${label}: error ${pkg_root#${repo_root}/}/${rel_file}" >&2
      overall_status=1
    fi
  fi
}

# Run TypeScript compiler type checking on packages with changed TS files
run_tsc_check() {
  if (( ${#ts_files[@]} == 0 )); then
    return 0
  fi

  local pnpm_cmd=""
  if command -v pnpm >/dev/null 2>&1; then
    pnpm_cmd="pnpm"
  elif command -v npm >/dev/null 2>&1; then
    pnpm_cmd="npm"
  else
    echo "TypeScript: no package manager found (pnpm/npm); skipping type check." >&2
    return 0
  fi

  # Group files by package to run tsc once per package
  declare -A pkg_ts_files
  local file dir pkg
  for file in "${ts_files[@]}"; do
    dir="$(dirname "${repo_root}/${file}")"
    pkg="$(find_pkg_root "${dir}" || true)"
    if [[ -z "${pkg}" ]]; then
      continue
    fi
    # Check if package has tsconfig.json
    if [[ ! -f "${pkg}/tsconfig.json" ]]; then
      continue
    fi
    pkg_ts_files["${pkg}"]=1
  done

  # Run tsc --noEmit for each package with changed TS files
  # Note: We check the entire package (not just changed files) because type errors
  # can appear in files that import the changed files. However, we filter output
  # to only show errors in changed files to avoid noise from pre-existing issues.
  local pkg
  for pkg in "${!pkg_ts_files[@]}"; do
    # Build a pattern to match changed files in this package
    local pkg_rel="${pkg#${repo_root}/}"
    local changed_pattern=""
    local file
    for file in "${ts_files[@]}"; do
      if [[ "${file}" == "${pkg_rel}/"* ]] || [[ "${pkg}" == "${repo_root}" && "${file}" != *"/"* ]]; then
        local rel_file="${file#${pkg_rel}/}"
        if [[ -z "${changed_pattern}" ]]; then
          changed_pattern="${rel_file}"
        else
          changed_pattern="${changed_pattern}|${rel_file}"
        fi
      fi
    done

    if [[ "${pnpm_cmd}" == "pnpm" ]]; then
      local tsc_output
      tsc_output="$(pnpm -C "${pkg}" exec tsc --noEmit 2>&1 || true)"
      if [[ -z "${tsc_output}" ]]; then
        echo "TypeScript: ok ${pkg#${repo_root}/}"
      else
        # Filter to only show errors in changed files
        local filtered_output
        if [[ -n "${changed_pattern}" ]]; then
          filtered_output="$(echo "${tsc_output}" | grep -E "(${changed_pattern})" || true)"
        else
          filtered_output="${tsc_output}"
        fi
        if [[ -n "${filtered_output}" ]]; then
          echo "TypeScript: errors in ${pkg#${repo_root}/} (changed files only)" >&2
          echo "${filtered_output}" | head -50 >&2
          overall_status=1
        else
          echo "TypeScript: ok ${pkg#${repo_root}/} (no errors in changed files)"
        fi
      fi
    else
      local tsc_output
      tsc_output="$(npm --prefix "${pkg}" exec -- tsc --noEmit 2>&1 || true)"
      if [[ -z "${tsc_output}" ]]; then
        echo "TypeScript: ok ${pkg#${repo_root}/}"
      else
        local filtered_output
        if [[ -n "${changed_pattern}" ]]; then
          filtered_output="$(echo "${tsc_output}" | grep -E "(${changed_pattern})" || true)"
        else
          filtered_output="${tsc_output}"
        fi
        if [[ -n "${filtered_output}" ]]; then
          echo "TypeScript: errors in ${pkg#${repo_root}/} (changed files only)" >&2
          echo "${filtered_output}" | head -50 >&2
          overall_status=1
        else
          echo "TypeScript: ok ${pkg#${repo_root}/} (no errors in changed files)"
        fi
      fi
    fi
  done
}

# Run Svelte type checking on packages with changed Svelte files
run_svelte_check() {
  if (( ${#svelte_files[@]} == 0 )); then
    return 0
  fi

  local pnpm_cmd=""
  if command -v pnpm >/dev/null 2>&1; then
    pnpm_cmd="pnpm"
  elif command -v npm >/dev/null 2>&1; then
    pnpm_cmd="npm"
  else
    echo "Svelte: no package manager found (pnpm/npm); skipping type check." >&2
    return 0
  fi

  # Group files by package
  declare -A pkg_svelte_files
  local file dir pkg
  for file in "${svelte_files[@]}"; do
    dir="$(dirname "${repo_root}/${file}")"
    pkg="$(find_pkg_root "${dir}" || true)"
    if [[ -z "${pkg}" ]]; then
      continue
    fi
    # Check if package has svelte-check available (check package.json for svelte-check dependency)
    if ! grep -q "svelte-check" "${pkg}/package.json" 2>/dev/null; then
      continue
    fi
    pkg_svelte_files["${pkg}"]=1
  done

  # Run svelte-check for each package with changed Svelte files
  # Note: We check the entire package but filter output to only show errors in changed files
  local pkg
  for pkg in "${!pkg_svelte_files[@]}"; do
    # Check if package has tsconfig.json (required for svelte-check)
    if [[ ! -f "${pkg}/tsconfig.json" ]]; then
      continue
    fi

    # Build a pattern to match changed files in this package
    local pkg_rel="${pkg#${repo_root}/}"
    local changed_pattern=""
    local file
    for file in "${svelte_files[@]}"; do
      if [[ "${file}" == "${pkg_rel}/"* ]] || [[ "${pkg}" == "${repo_root}" && "${file}" != *"/"* ]]; then
        local rel_file="${file#${pkg_rel}/}"
        if [[ -z "${changed_pattern}" ]]; then
          changed_pattern="${rel_file}"
        else
          changed_pattern="${changed_pattern}|${rel_file}"
        fi
      fi
    done

    if [[ "${pnpm_cmd}" == "pnpm" ]]; then
      local check_output=""
      # Try the check script first (for SvelteKit apps), then fall back to svelte-check directly
      if grep -q '"check"' "${pkg}/package.json" 2>/dev/null; then
        check_output="$(pnpm -C "${pkg}" run check --if-present 2>&1 || true)"
      else
        check_output="$(pnpm -C "${pkg}" exec svelte-check --tsconfig "${pkg}/tsconfig.json" 2>&1 || true)"
      fi
      
      if [[ -z "${check_output}" ]] || echo "${check_output}" | grep -qi "no issues found\|no errors\|✓" >/dev/null 2>&1; then
        echo "Svelte: ok ${pkg#${repo_root}/}"
      else
        # Filter to only show errors in changed files
        # Use -A 5 to include error messages and code snippets that appear after file paths
        local filtered_output
        if [[ -n "${changed_pattern}" ]]; then
          filtered_output="$(echo "${check_output}" | grep -E -A 5 "(${changed_pattern})" || true)"
        else
          filtered_output="${check_output}"
        fi
        if [[ -n "${filtered_output}" ]]; then
          echo "Svelte: errors in ${pkg#${repo_root}/} (changed files only)" >&2
          echo "${filtered_output}" | head -50 >&2
          overall_status=1
        else
          echo "Svelte: ok ${pkg#${repo_root}/} (no errors in changed files)"
        fi
      fi
    else
      local check_output=""
      if grep -q '"check"' "${pkg}/package.json" 2>/dev/null; then
        check_output="$(npm --prefix "${pkg}" run check --if-present 2>&1 || true)"
      else
        check_output="$(npm --prefix "${pkg}" exec -- svelte-check --tsconfig "${pkg}/tsconfig.json" 2>&1 || true)"
      fi
      
      if [[ -z "${check_output}" ]] || echo "${check_output}" | grep -qi "no issues found\|no errors\|✓" >/dev/null 2>&1; then
        echo "Svelte: ok ${pkg#${repo_root}/}"
      else
        # Filter to only show errors in changed files
        # Use -A 5 to include error messages and code snippets that appear after file paths
        local filtered_output
        if [[ -n "${changed_pattern}" ]]; then
          filtered_output="$(echo "${check_output}" | grep -E -A 5 "(${changed_pattern})" || true)"
        else
          filtered_output="${check_output}"
        fi
        if [[ -n "${filtered_output}" ]]; then
          echo "Svelte: errors in ${pkg#${repo_root}/} (changed files only)" >&2
          echo "${filtered_output}" | head -50 >&2
          overall_status=1
        else
          echo "Svelte: ok ${pkg#${repo_root}/} (no errors in changed files)"
        fi
      fi
    fi
  done
}

run_js_lint() {
  if (( ${#js_files[@]} == 0 )); then
    return 0
  fi

  local pnpm_cmd=""
  if command -v pnpm >/dev/null 2>&1; then
    pnpm_cmd="pnpm"
  elif command -v npm >/dev/null 2>&1; then
    pnpm_cmd="npm"
  else
    echo "JS/TS/Svelte/CSS/HTML: no package manager found (pnpm/npm); skipping." >&2
    return 0
  fi

  local file dir pkg pkg_rel rel_in_pkg
  for file in "${js_files[@]}"; do
    dir="$(dirname "${repo_root}/${file}")"
    pkg="$(find_pkg_root "${dir}" || true)"
    if [[ -z "${pkg}" ]]; then
      echo "JS/TS/Svelte/CSS/HTML: no package.json found for ${file}; skipping." >&2
      continue
    fi

    if [[ "${pkg}" == "${repo_root}" ]]; then
      rel_in_pkg="${file}"
    else
      pkg_rel="${pkg#${repo_root}/}"
      if [[ "${file}" != "${pkg_rel}/"* ]]; then
        echo "JS/TS/Svelte/CSS/HTML: could not map ${file} to ${pkg_rel}; skipping." >&2
        continue
      fi
      rel_in_pkg="${file#${pkg_rel}/}"
    fi

    case "${file}" in
      *.svelte) run_eslint_file "${pnpm_cmd}" "${pkg}" "${rel_in_pkg}" "Svelte" ;;
      *.ts|*.tsx) run_eslint_file "${pnpm_cmd}" "${pkg}" "${rel_in_pkg}" "TS" ;;
      *.css) run_eslint_file "${pnpm_cmd}" "${pkg}" "${rel_in_pkg}" "CSS" ;;
      *.html) run_eslint_file "${pnpm_cmd}" "${pkg}" "${rel_in_pkg}" "HTML" ;;
    esac
  done
}

run_yml_lint() {
  if (( ${#yml_files[@]} == 0 )); then
    return 0
  fi

  local yaml_linter=""
  # Try to find yamllint (Python-based YAML linter)
  if command -v yamllint >/dev/null 2>&1; then
    yaml_linter="yamllint_bin"
  elif [[ -n "${python_cmd}" ]] && "${python_cmd}" -m yamllint --version >/dev/null 2>&1; then
    yaml_linter="yamllint_module"
  elif [[ -n "${python_cmd}" ]] && "${python_cmd}" -c "import yaml" >/dev/null 2>&1; then
    yaml_linter="yaml_parse"
    echo "YAML: no yamllint found; running basic syntax check instead." >&2
  else
    echo "YAML: no YAML linter found (tried: yamllint); skipping." >&2
    return 0
  fi

  local file
  for file in "${yml_files[@]}"; do
    case "${yaml_linter}" in
      yamllint_bin)
        if yamllint "${file}" >/dev/null 2>&1; then
          echo "YAML: ok ${file}"
        else
          echo "YAML: error ${file}" >&2
          yamllint "${file}" >&2 || true
          overall_status=1
        fi
        ;;
      yamllint_module)
        if "${python_cmd}" -m yamllint "${file}" >/dev/null 2>&1; then
          echo "YAML: ok ${file}"
        else
          echo "YAML: error ${file}" >&2
          "${python_cmd}" -m yamllint "${file}" >&2 || true
          overall_status=1
        fi
        ;;
      yaml_parse)
        if "${python_cmd}" -c "import yaml; yaml.safe_load(open('${file}'))" >/dev/null 2>&1; then
          echo "YAML: ok ${file}"
        else
          echo "YAML: error ${file}" >&2
          "${python_cmd}" -c "import yaml; yaml.safe_load(open('${file}'))" >&2 || true
          overall_status=1
        fi
        ;;
    esac
  done
}

run_python_lint

# Run TypeScript and Svelte type checks first (these catch type errors that ESLint might miss)
run_tsc_check
run_svelte_check

# Then run ESLint for linting rules
run_js_lint

# Run YAML linting
run_yml_lint

if (( overall_status == 0 )); then
  echo "Done."
fi
exit "${overall_status}"
