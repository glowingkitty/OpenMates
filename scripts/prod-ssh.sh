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
if ! GIT_COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || [[ "$(basename "$GIT_COMMON_DIR")" != ".git" ]]; then
    printf '%s\n' "[prod-ssh] ERROR: Unable to resolve root control-plane checkout." >&2
    exit 1
fi
CONTROL_PLANE_ROOT="$(dirname "$GIT_COMMON_DIR")"
ENV_FILE="${CONTROL_PLANE_ROOT}/.env"
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

    # An expired/crashed master can leave its socket pathname behind. OpenSSH
    # otherwise authenticates successfully but disables multiplexing, leaving
    # an unusable background connection instead of replacing the dead socket.
    if [[ -e "$SOCK" || -L "$SOCK" ]]; then
        [[ -S "$SOCK" && -O "$SOCK" && ! -L "$SOCK" ]] || \
            die "Control path is not an owned Unix socket; leaving it unchanged."
        if ! master_active; then
            log "Removing stale control socket before authentication."
            rm -- "$SOCK"
        else
            log "Master connection already active — nothing to do."
            return 0
        fi
    fi

    log "Opening master connection to ${PROD_SSH_USER}@${PROD_SSH_HOST}"
    log "Prod-side temp-ssh-access window must be open (see scripts/temp-ssh-access.sh)."

    # Read OTP: prefer controlling terminal (interactive operator case); fall
    # back to stdin so Claude can pipe a code the user pasted into chat
    # (`./prod-ssh.sh open <<< 123456`). Never logged or persisted.
    local otp=""
    if [[ -t 0 ]]; then
        # Interactive terminal — prompt the operator directly
        read -r -s -p "[prod-ssh] TOTP code for ${PROD_SSH_USER}@${PROD_SSH_HOST}: " otp || die "Unable to read TOTP code."
        echo >&2
    else
        # Non-interactive (e.g. Claude's Bash tool) — read from stdin
        # Usage: echo "123456" | ./prod-ssh.sh open
        read -r otp || [[ -n "$otp" ]] || die "Unable to read TOTP code."
    fi
    [[ -n "$otp" ]] || die "Empty TOTP code."

    # Backgrounded master: -M -N -f keeps ssh running to hold the control socket.
    # expect feeds the 2-prompt keyboard-interactive flow; the key factor is
    # handled silently by ssh via -i.
    local expect_status=0
    PROD_SSH_PASSWORD="$PROD_SSH_PASSWORD" PROD_SSH_OTP="$otp" \
    expect <<'EXPECT_EOF' || expect_status=$?
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

# SSH can echo credentials. Report fixed messages, never the raw buffer.
log_user 0
set prompt_count 0
set password_sent 0
set otp_sent 0
proc fail {message code} {
    puts stderr "\[prod-ssh\] ERROR: $message"
    exit $code
}
proc send_otp {} {
    global otp_sent otp prompt_count
    if {$otp_sent} {
        fail "SSH requested another verification code; stopped to avoid reusing the TOTP. Check the access window and use a fresh code." 2
    }
    set otp_sent 1
    incr prompt_count
    send -- "$otp\r"
}
spawn ssh {*}$ssh_opts
expect {
    -nocase "*verification code:*" { send_otp; exp_continue -continue_timer }
    -nocase "*totp*:*" { send_otp; exp_continue -continue_timer }
    -nocase "*password:*" {
        if {$password_sent} {
            fail "SSH requested the password again; stopped to avoid repeated authentication attempts. Check PROD_SSH_PASSWORD in the canonical .env." 2
        }
        set password_sent 1
        incr prompt_count
        send -- "$password\r"
        exp_continue -continue_timer
    }
    -nocase "*permission denied*" {
        fail "SSH denied authentication; check the temporary key window, configured password, and fresh TOTP." 2
    }
    -nocase "*host key verification failed*" {
        fail "SSH host-key verification failed. Verify the production host identity and known_hosts entry manually." 2
    }
    -nocase "*are you sure you want to continue connecting*" {
        fail "SSH needs host-key confirmation. Verify the production host identity and register its known_hosts entry manually." 2
    }
    -nocase "*connection refused*" {
        fail "SSH connection refused. Check the production SSH access window, listener, and IP blocking on the server." 2
    }
    -nocase "*could not resolve hostname*" {
        fail "SSH could not resolve the configured production hostname. Check PROD_SSH_HOST and DNS." 2
    }
    -nocase "*connection timed out*" {
        fail "SSH connection timed out. Check network reachability and the production SSH access window." 3
    }
    timeout {
        fail "SSH timed out after $prompt_count authentication prompt(s). Check connectivity and the keyboard-interactive prompt format." 3
    }
    eof {}
}
if {[catch {wait} result] || [lindex $result 2] != 0} {
    fail "Unable to collect SSH exit status; master connection was not confirmed." 1
}
set ssh_status [lindex $result 3]
if {$ssh_status != 0} {
    fail "SSH exited with status $ssh_status after $prompt_count authentication prompt(s). Check the production SSH authentication logs and temporary access window; the TOTP alone does not confirm authentication." 1
}
exit 0
EXPECT_EOF

    unset otp PROD_SSH_OTP
    if (( expect_status != 0 )); then
        die "Master connection was not established (authentication helper status ${expect_status})."
    fi

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
