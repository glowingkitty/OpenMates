#!/usr/bin/env bash
set -euo pipefail

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

mapfile -d '' changed_files < <(
  {
    git diff --name-only -z --diff-filter=ACMRTUXB
    git diff --name-only -z --cached --diff-filter=ACMRTUXB
    git ls-files -z --others --exclude-standard
  } | awk 'BEGIN{RS="\0"; ORS="\0"} !seen[$0]++ {print}'
)

if (( ${#changed_files[@]} == 0 )); then
  echo "No uncommitted file changes."
  exit 0
fi

declare -a py_files=()
declare -a js_files=()

for path in "${changed_files[@]}"; do
  [[ -f "${path}" ]] || continue
  case "${path}" in
    *.py) py_files+=("${path}") ;;
    *.ts|*.tsx|*.svelte) js_files+=("${path}") ;;
  esac
done

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
    echo "JS/TS/Svelte: no package manager found (pnpm/npm); skipping." >&2
    return 0
  fi

  local file dir pkg pkg_rel rel_in_pkg
  for file in "${js_files[@]}"; do
    dir="$(dirname "${repo_root}/${file}")"
    pkg="$(find_pkg_root "${dir}" || true)"
    if [[ -z "${pkg}" ]]; then
      echo "JS/TS/Svelte: no package.json found for ${file}; skipping." >&2
      continue
    fi

    if [[ "${pkg}" == "${repo_root}" ]]; then
      rel_in_pkg="${file}"
    else
      pkg_rel="${pkg#${repo_root}/}"
      if [[ "${file}" != "${pkg_rel}/"* ]]; then
        echo "JS/TS/Svelte: could not map ${file} to ${pkg_rel}; skipping." >&2
        continue
      fi
      rel_in_pkg="${file#${pkg_rel}/}"
    fi

    case "${file}" in
      *.svelte) run_eslint_file "${pnpm_cmd}" "${pkg}" "${rel_in_pkg}" "Svelte" ;;
      *.ts|*.tsx) run_eslint_file "${pnpm_cmd}" "${pkg}" "${rel_in_pkg}" "TS" ;;
    esac
  done
}

run_python_lint
run_js_lint

if (( overall_status == 0 )); then
  echo "Done."
fi
exit "${overall_status}"
