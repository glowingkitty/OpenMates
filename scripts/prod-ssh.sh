#!/usr/bin/env bash
# scripts/prod-ssh.sh
#
# Claude-friendly wrapper around SSH to the production server, which enforces
# 3-factor auth (key + password + TOTP).
#
# Uses OpenSSH ControlMaster multiplexing so the user only types the TOTP once
# per working session — all subsequent commands reuse the authenticated socket.
#
# Usage:
#   ./prod-ssh.sh open                  # prompt for TOTP, establish master (persists ~30m)
#   ./prod-ssh.sh "<remote command>"    # run a command over the existing master
#   ./prod-ssh.sh                       # interactive shell (requires an open master)
#   ./prod-ssh.sh close                 # tear down master early
#   ./prod-ssh.sh status                # is a master currently active?
#
# Prerequisites:
#   - `expect` installed:  sudo apt install -y expect
#   - PROD_SSH_HOST, PROD_SSH_USER, PROD_SSH_KEY, PROD_SSH_PASSWORD set in .env
#   - Temporary SSH window opened on prod via scripts/temp-ssh-access.sh
#
# Security properties:
#   - Password lives only in .env (gitignored, chmod 600 recommended) and in the
#     expect process memory; never on a command line, never logged.
#   - TOTP is read from /dev/tty per `open` call, never stored.
#   - ControlPath socket is in $HOME/.ssh/ with mode 600 implicitly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
SOCK_DIR="${HOME}/.ssh/prod-ssh-sockets"
PERSIST_DURATION="${PROD_SSH_PERSIST:-30m}"

log()  { echo "[prod-ssh] $*" >&2; }
die()  { echo "[prod-ssh] ERROR: $*" >&2; exit 1; }

# ── Load config ──────────────────────────────────────────────────────────────

[[ -f "$ENV_FILE" ]] || die ".env not found at $ENV_FILE"
set +u  # .env may reference unset vars (e.g. password with special chars)
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
set -u

: "${PROD_SSH_HOST:?PROD_SSH_HOST missing from .env}"
: "${PROD_SSH_USER:?PROD_SSH_USER missing from .env}"
: "${PROD_SSH_KEY:?PROD_SSH_KEY missing from .env}"
: "${PROD_SSH_PASSWORD:?PROD_SSH_PASSWORD missing from .env}"

# Expand ~ in key path
PROD_SSH_KEY="${PROD_SSH_KEY/#\~/$HOME}"
[[ -f "$PROD_SSH_KEY" ]] || die "SSH key not found: $PROD_SSH_KEY"

mkdir -p "$SOCK_DIR"
chmod 700 "$SOCK_DIR"
SOCK="${SOCK_DIR}/${PROD_SSH_USER}@${PROD_SSH_HOST}.sock"

SSH_OPTS=(
    -i "$PROD_SSH_KEY"
    -o "ControlMaster=auto"
    -o "ControlPath=${SOCK}"
    -o "ControlPersist=${PERSIST_DURATION}"
    -o "PreferredAuthentications=publickey,keyboard-interactive"
    -o "PubkeyAuthentication=yes"
    -o "ServerAliveInterval=30"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

master_active() {
    ssh -O check "${SSH_OPTS[@]}" "${PROD_SSH_USER}@${PROD_SSH_HOST}" 2>/dev/null
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_open() {
    if master_active; then
        log "Master connection already active — nothing to do."
        log "  Close it with: $0 close"
        return 0
    fi

    command -v expect >/dev/null 2>&1 || \
        die "expect is not installed. Run: sudo apt install -y expect"

    log "Opening master connection to ${PROD_SSH_USER}@${PROD_SSH_HOST}"
    log "Prod-side temp-ssh-access window must be open (see scripts/temp-ssh-access.sh)."

    # Read OTP: prefer controlling terminal (interactive operator case); fall
    # back to stdin so Claude can pipe a code the user pasted into chat
    # (`./prod-ssh.sh open <<< 123456`). Never logged or persisted.
    local otp=""
    if [[ -t 0 ]]; then
        # Interactive terminal — prompt the operator directly
        read -r -s -p "[prod-ssh] TOTP code for ${PROD_SSH_USER}@${PROD_SSH_HOST}: " otp
        echo >&2
    else
        # Non-interactive (e.g. Claude's Bash tool) — read from stdin
        # Usage: echo "123456" | ./prod-ssh.sh open
        read -r otp
    fi
    [[ -n "$otp" ]] || die "Empty TOTP code."

    # Backgrounded master: -M -N -f keeps ssh running to hold the control socket.
    # expect feeds the 2-prompt keyboard-interactive flow; the key factor is
    # handled silently by ssh via -i.
    PROD_SSH_PASSWORD="$PROD_SSH_PASSWORD" PROD_SSH_OTP="$otp" \
    expect <<'EXPECT_EOF'
set timeout 30
set password $env(PROD_SSH_PASSWORD)
set otp      $env(PROD_SSH_OTP)

# Rebuild ssh argv from env so we don't have to pass it through expect quoting
set ssh_opts [list \
    "-i" $env(PROD_SSH_KEY) \
    "-o" "ControlMaster=auto" \
    "-o" "ControlPath=$env(SOCK)" \
    "-o" "ControlPersist=$env(PERSIST_DURATION)" \
    "-o" "PreferredAuthentications=publickey,keyboard-interactive" \
    "-o" "PubkeyAuthentication=yes" \
    "-o" "ServerAliveInterval=30" \
    "-M" "-N" "-f" \
    "$env(PROD_SSH_USER)@$env(PROD_SSH_HOST)" \
]

log_user 0
eval spawn ssh $ssh_opts
expect {
    -nocase "assword:"            { send -- "$password\r"; exp_continue }
    -nocase "erification code:"   { send -- "$otp\r";      exp_continue }
    -nocase "permission denied"   { puts stderr "\n[prod-ssh] ssh denied — check key window / password / OTP"; exit 2 }
    timeout                       { puts stderr "\n[prod-ssh] ssh timed out waiting for prompt"; exit 3 }
    eof
}
catch wait result
exit [lindex $result 3]
EXPECT_EOF

    unset PROD_SSH_OTP

    if master_active; then
        log "Master connection established (persists ${PERSIST_DURATION} idle)."
        log "Run commands: $0 \"docker logs api --tail 50\""
    else
        die "Failed to establish master connection."
    fi
}

cmd_close() {
    if ! master_active; then
        log "No active master connection."
        return 0
    fi
    ssh -O exit "${SSH_OPTS[@]}" "${PROD_SSH_USER}@${PROD_SSH_HOST}" 2>/dev/null || true
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
    ssh "${SSH_OPTS[@]}" "${PROD_SSH_USER}@${PROD_SSH_HOST}" "$@"
}

cmd_shell() {
    if ! master_active; then
        die "No active master connection. Run: $0 open"
    fi
    ssh "${SSH_OPTS[@]}" "${PROD_SSH_USER}@${PROD_SSH_HOST}"
}

# Export for expect subshell
export PROD_SSH_KEY PROD_SSH_USER PROD_SSH_HOST SOCK PERSIST_DURATION

case "${1:-shell}" in
    open)    cmd_open ;;
    close)   cmd_close ;;
    status)  cmd_status ;;
    shell)   cmd_shell ;;
    -h|--help|help)
        sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    *)       cmd_run "$@" ;;
esac
