#!/usr/bin/env bash
# scripts/preview-ssh.sh
#
# Codex-friendly wrapper around SSH to the isolated preview server. It mirrors
# scripts/prod-ssh.sh but targets preview.openmates.org and uses a separate
# ControlMaster socket so preview access cannot collide with core or upload.
# Resolves the private .env from the canonical checkout when used in a worktree.
#
# Usage:
#   ./scripts/preview-ssh.sh open                  # prompt/read TOTP, establish master
#   ./scripts/preview-ssh.sh "docker ps"           # run command over existing master
#   ./scripts/preview-ssh.sh                       # interactive shell
#   ./scripts/preview-ssh.sh close                 # tear down master early
#   ./scripts/preview-ssh.sh status                # check master status
#
# Config in .env:
#   PREVIEW_SSH_HOST       optional, defaults to preview.openmates.org
#   PREVIEW_SSH_USER       optional, defaults to PROD_SSH_USER or superdev
#   PREVIEW_SSH_KEY        optional, defaults to ~/.ssh/id_ed25519
#   PREVIEW_SSH_PASSWORD   optional, defaults to PROD_SSH_PASSWORD
#   PREVIEW_SSH_PERSIST    optional, defaults to PROD_SSH_PERSIST or 30m

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! GIT_COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || [[ "$(basename "$GIT_COMMON_DIR")" != ".git" ]]; then
    printf '%s\n' "[preview-ssh] ERROR: Unable to resolve root control-plane checkout." >&2
    exit 1
fi
CONTROL_PLANE_ROOT="$(dirname "$GIT_COMMON_DIR")"
ENV_FILE="${CONTROL_PLANE_ROOT}/.env"
SOCK_DIR="${HOME}/.ssh/preview-ssh-sockets"

log()  { echo "[preview-ssh] $*" >&2; }
die()  { echo "[preview-ssh] ERROR: $*" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || die ".env not found at $ENV_FILE"
set +u
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
set -u

PREVIEW_SSH_HOST="${PREVIEW_SSH_HOST:-preview.openmates.org}"
PREVIEW_SSH_USER="${PREVIEW_SSH_USER:-${PROD_SSH_USER:-superdev}}"
PREVIEW_SSH_KEY="${PREVIEW_SSH_KEY:-~/.ssh/id_ed25519}"
PREVIEW_SSH_PASSWORD="${PREVIEW_SSH_PASSWORD:-${PROD_SSH_PASSWORD:-}}"
PREVIEW_SSH_PERSIST="${PREVIEW_SSH_PERSIST:-${PROD_SSH_PERSIST:-30m}}"

: "${PREVIEW_SSH_HOST:?PREVIEW_SSH_HOST missing}"
: "${PREVIEW_SSH_USER:?PREVIEW_SSH_USER missing}"
: "${PREVIEW_SSH_KEY:?PREVIEW_SSH_KEY missing}"
: "${PREVIEW_SSH_PASSWORD:?PREVIEW_SSH_PASSWORD missing and PROD_SSH_PASSWORD not set}"

PREVIEW_SSH_KEY="${PREVIEW_SSH_KEY/#\~/$HOME}"
[[ -f "$PREVIEW_SSH_KEY" ]] || die "SSH key not found: $PREVIEW_SSH_KEY"

mkdir -p "$SOCK_DIR"
chmod 700 "$SOCK_DIR"
SOCK="${SOCK_DIR}/${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}.sock"

SSH_OPTS=(
    -i "$PREVIEW_SSH_KEY"
    -o "IdentitiesOnly=yes"
    -o "ControlMaster=auto"
    -o "ControlPath=${SOCK}"
    -o "ControlPersist=${PREVIEW_SSH_PERSIST}"
    -o "PreferredAuthentications=publickey,keyboard-interactive"
    -o "PubkeyAuthentication=yes"
    -o "ServerAliveInterval=30"
)

master_active() {
    ssh -O check "${SSH_OPTS[@]}" "${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}" 2>/dev/null
}

cmd_open() {
    if master_active; then
        log "Master connection already active."
        log "Close it with: $0 close"
        return 0
    fi
    if [[ -S "$SOCK" ]]; then
        rm -f "$SOCK"
    fi

    command -v expect >/dev/null 2>&1 || \
        die "expect is not installed. Run: sudo apt install -y expect"

    log "Opening master connection to ${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}"
    log "Preview-side temp-ssh-access window must be open."

    local otp=""
    if [[ -t 0 ]]; then
        read -r -s -p "[preview-ssh] TOTP code for ${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}: " otp
        echo >&2
    else
        read -r otp
    fi
    [[ -n "$otp" ]] || die "Empty TOTP code."

    PREVIEW_SSH_PASSWORD="$PREVIEW_SSH_PASSWORD" PREVIEW_SSH_OTP="$otp" \
    expect <<'EXPECT_EOF'
set timeout 45
set password $env(PREVIEW_SSH_PASSWORD)
set otp      $env(PREVIEW_SSH_OTP)

set ssh_opts [list \
    "-i" $env(PREVIEW_SSH_KEY) \
    "-o" "IdentitiesOnly=yes" \
    "-o" "ControlMaster=auto" \
    "-o" "ControlPath=$env(SOCK)" \
    "-o" "ControlPersist=$env(PREVIEW_SSH_PERSIST)" \
    "-o" "PreferredAuthentications=publickey,keyboard-interactive" \
    "-o" "PubkeyAuthentication=yes" \
    "-o" "ServerAliveInterval=30" \
    "-M" "-N" "-f" \
    "$env(PREVIEW_SSH_USER)@$env(PREVIEW_SSH_HOST)" \
]

log_user 0
spawn ssh {*}$ssh_opts
expect {
    -nocase "assword:"          { send -- "$password\r"; exp_continue }
    -nocase "verification code" { send -- "$otp\r";      exp_continue }
    -nocase "one-time password" { send -- "$otp\r";      exp_continue }
    -nocase "totp"              { send -- "$otp\r";      exp_continue }
    -nocase "authenticator"     { send -- "$otp\r";      exp_continue }
    -nocase "permission denied" { puts stderr "\npreview ssh denied - check key window, password, or OTP"; exit 2 }
    -nocase "connection refused" { puts stderr "\npreview ssh connection refused - likely fail2ban or sshd unavailable"; exit 4 }
    timeout                     { puts stderr "\npreview ssh timed out waiting for prompt"; exit 3 }
    eof
}
catch wait result
exit [lindex $result 3]
EXPECT_EOF

    unset PREVIEW_SSH_OTP

    if master_active; then
        log "Master connection established (persists ${PREVIEW_SSH_PERSIST} idle)."
        log "Run commands: $0 \"docker ps\""
    else
        die "Failed to establish master connection."
    fi
}

cmd_close() {
    if ! master_active; then
        log "No active master connection."
        return 0
    fi
    ssh -O exit "${SSH_OPTS[@]}" "${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}" 2>/dev/null || true
    log "Master connection closed."
}

cmd_status() {
    if master_active; then
        log "Master connection ACTIVE (socket: ${SOCK})"
    else
        log "No active master connection. Run: $0 open"
    fi
}

cmd_run() {
    if ! master_active; then
        die "No active master connection. Run: $0 open"
    fi
    # shellcheck disable=SC2029
    ssh "${SSH_OPTS[@]}" "${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}" "$@"
}

cmd_shell() {
    if ! master_active; then
        die "No active master connection. Run: $0 open"
    fi
    ssh "${SSH_OPTS[@]}" "${PREVIEW_SSH_USER}@${PREVIEW_SSH_HOST}"
}

export PREVIEW_SSH_KEY PREVIEW_SSH_USER PREVIEW_SSH_HOST SOCK PREVIEW_SSH_PERSIST

case "${1:-shell}" in
    open)    cmd_open ;;
    close)   cmd_close ;;
    status)  cmd_status ;;
    shell)   cmd_shell ;;
    -h|--help|help)
        sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    *)       cmd_run "$@" ;;
esac
