#!/usr/bin/env bash
# scripts/upload-ssh.sh
#
# Claude-friendly wrapper around SSH to the isolated upload server. It mirrors
# scripts/prod-ssh.sh but targets upload.openmates.org and uses a separate
# ControlMaster socket so upload access cannot collide with the main prod host.
#
# Usage:
#   ./scripts/upload-ssh.sh open                  # prompt/read TOTP, establish master
#   ./scripts/upload-ssh.sh "docker ps"           # run command over existing master
#   ./scripts/upload-ssh.sh                       # interactive shell
#   ./scripts/upload-ssh.sh close                 # tear down master early
#   ./scripts/upload-ssh.sh status                # check master status
#
# Config in .env:
#   UPLOAD_SSH_HOST       optional, defaults to upload.openmates.org
#   UPLOAD_SSH_USER       optional, defaults to PROD_SSH_USER or superdev
#   UPLOAD_SSH_KEY        optional, defaults to ~/.ssh/id_ed25519
#   UPLOAD_SSH_PASSWORD   optional, defaults to PROD_SSH_PASSWORD
#   UPLOAD_SSH_PERSIST    optional, defaults to PROD_SSH_PERSIST or 30m

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
SOCK_DIR="${HOME}/.ssh/upload-ssh-sockets"

log()  { echo "[upload-ssh] $*" >&2; }
die()  { echo "[upload-ssh] ERROR: $*" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || die ".env not found at $ENV_FILE"
set +u
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
set -u

UPLOAD_SSH_HOST="${UPLOAD_SSH_HOST:-upload.openmates.org}"
UPLOAD_SSH_USER="${UPLOAD_SSH_USER:-${PROD_SSH_USER:-superdev}}"
UPLOAD_SSH_KEY="${UPLOAD_SSH_KEY:-~/.ssh/id_ed25519}"
UPLOAD_SSH_PASSWORD="${UPLOAD_SSH_PASSWORD:-${PROD_SSH_PASSWORD:-}}"
UPLOAD_SSH_PERSIST="${UPLOAD_SSH_PERSIST:-${PROD_SSH_PERSIST:-30m}}"

: "${UPLOAD_SSH_HOST:?UPLOAD_SSH_HOST missing}"
: "${UPLOAD_SSH_USER:?UPLOAD_SSH_USER missing}"
: "${UPLOAD_SSH_KEY:?UPLOAD_SSH_KEY missing}"
: "${UPLOAD_SSH_PASSWORD:?UPLOAD_SSH_PASSWORD missing and PROD_SSH_PASSWORD not set}"

UPLOAD_SSH_KEY="${UPLOAD_SSH_KEY/#\~/$HOME}"
[[ -f "$UPLOAD_SSH_KEY" ]] || die "SSH key not found: $UPLOAD_SSH_KEY"

mkdir -p "$SOCK_DIR"
chmod 700 "$SOCK_DIR"
SOCK="${SOCK_DIR}/${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}.sock"

SSH_OPTS=(
    -i "$UPLOAD_SSH_KEY"
    -o "IdentitiesOnly=yes"
    -o "ControlMaster=auto"
    -o "ControlPath=${SOCK}"
    -o "ControlPersist=${UPLOAD_SSH_PERSIST}"
    -o "PreferredAuthentications=publickey,keyboard-interactive"
    -o "PubkeyAuthentication=yes"
    -o "ServerAliveInterval=30"
)

master_active() {
    ssh -O check "${SSH_OPTS[@]}" "${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}" 2>/dev/null
}

cmd_open() {
    if master_active; then
        log "Master connection already active."
        log "Close it with: $0 close"
        return 0
    fi

    command -v expect >/dev/null 2>&1 || \
        die "expect is not installed. Run: sudo apt install -y expect"

    log "Opening master connection to ${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}"
    log "Upload-side temp-ssh-access window must be open."

    local otp=""
    if [[ -t 0 ]]; then
        read -r -s -p "[upload-ssh] TOTP code for ${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}: " otp
        echo >&2
    else
        read -r otp
    fi
    [[ -n "$otp" ]] || die "Empty TOTP code."

    UPLOAD_SSH_PASSWORD="$UPLOAD_SSH_PASSWORD" UPLOAD_SSH_OTP="$otp" \
    expect <<'EXPECT_EOF'
set timeout 45
set password $env(UPLOAD_SSH_PASSWORD)
set otp      $env(UPLOAD_SSH_OTP)

set ssh_opts [list \
    "-i" $env(UPLOAD_SSH_KEY) \
    "-o" "IdentitiesOnly=yes" \
    "-o" "ControlMaster=auto" \
    "-o" "ControlPath=$env(SOCK)" \
    "-o" "ControlPersist=$env(UPLOAD_SSH_PERSIST)" \
    "-o" "PreferredAuthentications=publickey,keyboard-interactive" \
    "-o" "PubkeyAuthentication=yes" \
    "-o" "ServerAliveInterval=30" \
    "-M" "-N" "-f" \
    "$env(UPLOAD_SSH_USER)@$env(UPLOAD_SSH_HOST)" \
]

log_user 0
eval spawn ssh $ssh_opts
expect {
    -nocase "assword:"          { send -- "$password\r"; exp_continue }
    -nocase "verification code" { send -- "$otp\r";      exp_continue }
    -nocase "one-time password" { send -- "$otp\r";      exp_continue }
    -nocase "totp"              { send -- "$otp\r";      exp_continue }
    -nocase "authenticator"     { send -- "$otp\r";      exp_continue }
    -nocase "permission denied" { puts stderr "\nupload ssh denied - check key window, password, or OTP"; exit 2 }
    -nocase "connection refused" { puts stderr "\nupload ssh connection refused - likely fail2ban or sshd unavailable"; exit 4 }
    timeout                     { puts stderr "\nupload ssh timed out waiting for prompt"; exit 3 }
    eof
}
catch wait result
exit [lindex $result 3]
EXPECT_EOF

    unset UPLOAD_SSH_OTP

    if master_active; then
        log "Master connection established (persists ${UPLOAD_SSH_PERSIST} idle)."
        log "Run commands: $0 \"docker logs app-uploads --tail 50\""
    else
        die "Failed to establish master connection."
    fi
}

cmd_close() {
    if ! master_active; then
        log "No active master connection."
        return 0
    fi
    ssh -O exit "${SSH_OPTS[@]}" "${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}" 2>/dev/null || true
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
    ssh "${SSH_OPTS[@]}" "${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}" "$@"
}

cmd_shell() {
    if ! master_active; then
        die "No active master connection. Run: $0 open"
    fi
    ssh "${SSH_OPTS[@]}" "${UPLOAD_SSH_USER}@${UPLOAD_SSH_HOST}"
}

export UPLOAD_SSH_KEY UPLOAD_SSH_USER UPLOAD_SSH_HOST SOCK UPLOAD_SSH_PERSIST

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
