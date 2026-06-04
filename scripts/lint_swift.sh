#!/usr/bin/env bash
set -euo pipefail

# Linux-friendly SwiftLint wrapper for agent/deploy workflows.
# Uses local swiftlint when available, otherwise a cached Docker image.
# Set OPENMATES_SWIFTLINT_AUTO_PULL=1 to pull the Docker image on demand.
# Set OPENMATES_SWIFTLINT_REQUIRED=1 to fail when SwiftLint is unavailable.

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  echo "SwiftLint: error: must be run inside a git repo" >&2
  exit 2
fi

cd "${repo_root}"

config_path="${repo_root}/.swiftlint.yml"
image="${OPENMATES_SWIFTLINT_IMAGE:-ghcr.io/realm/swiftlint:latest}"
auto_pull="${OPENMATES_SWIFTLINT_AUTO_PULL:-0}"
required="${OPENMATES_SWIFTLINT_REQUIRED:-0}"
full_repo=false
declare -a target_paths=()
declare -a swift_files=()

usage() {
  cat <<'EOF'
Usage: scripts/lint_swift.sh [full_repo] [--path <file|dir>] [-- <file|dir> ...]

Runs SwiftLint for Apple Swift files. Uses local `swiftlint` first, then a
cached Docker image (`ghcr.io/realm/swiftlint:latest`). By default the script
skips cleanly if SwiftLint is unavailable so Linux agents do not block on a
missing image.

Environment:
  OPENMATES_SWIFTLINT_AUTO_PULL=1   Pull Docker image if missing
  OPENMATES_SWIFTLINT_REQUIRED=1    Fail if no SwiftLint runner is available
  OPENMATES_SWIFTLINT_IMAGE=...     Override Docker image
EOF
}

normalize_target_path() {
  local raw_path="$1"
  local normalized="${raw_path}"

  [[ -n "${raw_path}" ]] || return 1

  if [[ "${raw_path}" = /* ]]; then
    if [[ "${raw_path}" == "${repo_root}"* ]]; then
      normalized="${raw_path#${repo_root}/}"
    else
      echo "SwiftLint: target path is outside repo: ${raw_path}" >&2
      return 1
    fi
  fi

  normalized="${normalized#./}"
  [[ -n "${normalized}" ]] || return 1
  printf '%s\n' "${normalized}"
}

matches_target_path() {
  local file_path="$1"
  local target_path="$2"

  [[ "${file_path}" == "${target_path}" || "${file_path}" == "${target_path}/"* ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    full_repo)
      full_repo=true
      shift
      ;;
    --path)
      if [[ -z "${2-}" ]]; then
        echo "SwiftLint: missing value for --path" >&2
        exit 1
      fi
      target_paths+=("$2")
      shift 2
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        target_paths+=("$1")
        shift
      done
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    -* )
      echo "SwiftLint: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      target_paths+=("$1")
      shift
      ;;
  esac
done

if [[ ! -f "${config_path}" ]]; then
  echo "SwiftLint: .swiftlint.yml not found; skipping." >&2
  exit 0
fi

declare -a candidate_files=()
if ${full_repo}; then
  mapfile -d '' candidate_files < <(git ls-files -z -- 'apple/**/*.swift')
else
  mapfile -d '' candidate_files < <(
    {
      git diff --name-only -z --diff-filter=ACMRTUXB -- 'apple/**/*.swift'
      git diff --name-only -z --cached --diff-filter=ACMRTUXB -- 'apple/**/*.swift'
      git ls-files -z --others --exclude-standard -- 'apple/**/*.swift'
    } | awk 'BEGIN{RS="\0"; ORS="\0"} !seen[$0]++ {print}'
  )
fi

if (( ${#target_paths[@]} > 0 )); then
  declare -a normalized_targets=()
  for target in "${target_paths[@]}"; do
    normalized_target="$(normalize_target_path "${target}" || true)"
    [[ -n "${normalized_target}" ]] && normalized_targets+=("${normalized_target}")
  done

  # Explicit --path arguments should work for unchanged files too. This keeps
  # agent verification fast and predictable for a single Swift file.
  if ! ${full_repo}; then
    for target in "${normalized_targets[@]}"; do
      if [[ -f "${target}" && "${target}" == *.swift ]]; then
        candidate_files+=("${target}")
      elif [[ -d "${target}" ]]; then
        while IFS= read -r -d '' file; do
          candidate_files+=("${file}")
        done < <(git ls-files -z -- "${target}/**/*.swift" "${target}/*.swift")
      fi
    done
  fi

  for file in "${candidate_files[@]}"; do
    for target in "${normalized_targets[@]}"; do
      if matches_target_path "${file}" "${target}"; then
        swift_files+=("${file}")
        break
      fi
    done
  done
else
  swift_files=("${candidate_files[@]}")
fi

if (( ${#swift_files[@]} == 0 )); then
  echo "SwiftLint: no matching Swift files."
  exit 0
fi

run_swiftlint() {
  local runner="$1"
  shift

  local index=0
  export SCRIPT_INPUT_FILE_COUNT="${#swift_files[@]}"
  for file in "${swift_files[@]}"; do
    export "SCRIPT_INPUT_FILE_${index}=${repo_root}/${file}"
    index=$((index + 1))
  done

  "${runner}" lint --config "${config_path}" --use-script-input-files "$@"
}

if command -v swiftlint >/dev/null 2>&1; then
  echo "SwiftLint: using local swiftlint (${#swift_files[@]} file(s))"
  run_swiftlint swiftlint
  exit $?
fi

if command -v docker >/dev/null 2>&1; then
  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    if [[ "${auto_pull}" == "1" ]]; then
      echo "SwiftLint: pulling ${image}..." >&2
      docker pull "${image}" >&2
    else
      echo "SwiftLint: SKIPPED — ${image} is not cached." >&2
      echo "  Run: OPENMATES_SWIFTLINT_AUTO_PULL=1 scripts/lint_swift.sh --path apple" >&2
      if [[ "${required}" == "1" ]]; then
        exit 1
      fi
      exit 0
    fi
  fi

  echo "SwiftLint: using Docker image ${image} (${#swift_files[@]} file(s))"
  docker run --rm \
    -v "${repo_root}:${repo_root}" \
    -w "${repo_root}" \
    -e SCRIPT_INPUT_FILE_COUNT="${#swift_files[@]}" \
    $(for index in "${!swift_files[@]}"; do printf -- '-e SCRIPT_INPUT_FILE_%s=%q ' "${index}" "${repo_root}/${swift_files[$index]}"; done) \
    "${image}" \
    swiftlint lint --config "${config_path}" --use-script-input-files
  exit $?
fi

echo "SwiftLint: SKIPPED — neither swiftlint nor Docker is available." >&2
if [[ "${required}" == "1" ]]; then
  exit 1
fi
exit 0
