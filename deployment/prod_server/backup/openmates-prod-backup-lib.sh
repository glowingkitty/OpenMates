#!/usr/bin/env bash
# Shared settings and helpers for the OpenMates production backup scripts
# (openmates-prod-backup.sh and the restore drill). Sourced, not run.
# Secrets never appear in process arguments or output: the Vault token goes over
# stdin, S3 keys only live in the exported environment of the calling process.

INSTALL_PATH="${OPENMATES_INSTALL_PATH:-/home/superdev/openmates}"
BUCKET="${OPENMATES_BACKUP_BUCKET:-}"
REGION="${OPENMATES_BACKUP_REGION:-}"
ENDPOINT="${OPENMATES_BACKUP_ENDPOINT:-https://${REGION}.your-objectstorage.com}"
PREFIX="${OPENMATES_BACKUP_PREFIX:-prod/nightly}"
STATE_KEY="${OPENMATES_BACKUP_STATE_KEY:-prod/state/latest.json}"
KEEP_COPIES="${OPENMATES_BACKUP_KEEP_COPIES:-7}"
RECIPIENT_FILE="${OPENMATES_BACKUP_RECIPIENT_FILE:-$HOME/.config/openmates-backup/recipient.asc}"
STATE_DIR="${OPENMATES_BACKUP_STATE_DIR:-$HOME/.local/state/openmates-backup}"
WORK_ROOT="${INSTALL_PATH}/backups/core/nightly-work"
VAULT_CONTAINER="${OPENMATES_BACKUP_VAULT_CONTAINER:-vault}"
API_CONTAINER="${OPENMATES_BACKUP_API_CONTAINER:-api}"
AWS_CLI_IMAGE="${OPENMATES_BACKUP_AWS_CLI_IMAGE:-amazon/aws-cli:2.27.50}"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

current_step="start"
step() { current_step="$1"; printf '%s\n' "$1" > "${STATE_DIR}/current-step"; log "step: $1"; }

env_value() {
  # Last assignment wins, like docker compose; quotes around the value are stripped.
  local name="$1"
  awk -v n="$name" 'index($0, n "=") == 1 { v = substr($0, length(n) + 2) } END { print v }' \
    "${INSTALL_PATH}/.env" | sed -e "s/^'\(.*\)'$/\1/" -e 's/^"\(.*\)"$/\1/'
}

discord() {
  local message="$1" webhook
  webhook="$(env_value OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION)"
  if [[ -z "$webhook" ]]; then
    log "ERROR: no Discord webhook configured; alert not sent: ${message}"
    return 1
  fi
  python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1][:1900]}))' "$message" |
    curl -fsS --max-time 20 -H 'Content-Type: application/json' --data-binary @- "$webhook" >/dev/null
}

vault_field() {
  # Reads one KV field with the API service token. The token goes over stdin,
  # never into a process argument list.
  local path="$1" field="$2"
  docker exec "$API_CONTAINER" cat /vault-data/api.token |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" \
      sh -c 'read -r VAULT_TOKEN; export VAULT_TOKEN; exec vault kv get -mount=kv -field="$1" "$2"' \
      sh "$field" "$path"
}

s3() {
  if command -v aws >/dev/null 2>&1; then
    aws --endpoint-url "$ENDPOINT" --region "$REGION" "$@"
  else
    docker run --rm -i --network host -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
      -v "${WORK_ROOT}:${WORK_ROOT}" "$AWS_CLI_IMAGE" \
      --endpoint-url "$ENDPOINT" --region "$REGION" "$@"
  fi
}

unpause_vault() {
  if [[ "$(docker inspect -f '{{.State.Paused}}' "$VAULT_CONTAINER" 2>/dev/null)" == "true" ]]; then
    docker unpause "$VAULT_CONTAINER" >/dev/null
    log "vault unpaused"
  fi
}

load_s3_credentials() {
  AWS_ACCESS_KEY_ID="$(vault_field providers/hetzner s3_access_key)"
  AWS_SECRET_ACCESS_KEY="$(vault_field providers/hetzner s3_secret_key)"
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  [[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" ]]
}

require_storage_settings() {
  [[ -n "$BUCKET" && -n "$REGION" ]] || { log "ERROR: OPENMATES_BACKUP_BUCKET and OPENMATES_BACKUP_REGION are required"; return 1; }
}
