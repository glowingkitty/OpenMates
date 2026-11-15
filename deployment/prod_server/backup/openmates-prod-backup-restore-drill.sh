#!/usr/bin/env bash
# Restore drill for the nightly production backup (TASK-5693).
#
# Proves that one uploaded backup is usable, without touching the live stack:
#   1. downloads the newest copy (or --object <key>) from object storage,
#   2. decrypts it with the private key read from stdin (the off-prod recovery
#      copy; it lives only in a throwaway GnuPG home that is deleted at the end),
#   3. checks every checksum,
#   4. restores the Postgres dump into a throwaway container without network,
#   5. starts a throwaway Vault from the snapshot, unseals it with the restored
#      unseal key and, with the restored service token, decrypts one
#      server-encrypted username from the restored database (only success and
#      length are reported; the plaintext is never printed),
#   6. removes every container, volume and file it created.
#
# Usage (from the dev host):
#   ./scripts/prod-ssh.sh "~/openmates-backup/openmates-prod-backup-restore-drill.sh --key-stdin" \
#     < <recovery-private-key.asc>
set -Eeuo pipefail
umask 077

# shellcheck source=openmates-prod-backup-lib.sh
source "$(dirname "$(readlink -f "$0")")/openmates-prod-backup-lib.sh"

object=""
key_from_stdin=0
while (( $# )); do
  case "$1" in
    --object) object="$2"; shift 2 ;;
    --key-stdin) key_from_stdin=1; shift ;;
    *) echo "usage: $0 --key-stdin [--object <key>]" >&2; exit 64 ;;
  esac
done
(( key_from_stdin )) || { echo "the private key must be passed on stdin (--key-stdin)" >&2; exit 64; }
require_storage_settings

drill_id="restore-drill-$(date -u +%Y%m%dT%H%M%SZ)"
WORK_ROOT="${INSTALL_PATH}/backups/core/${drill_id}"
pg_name="openmates-${drill_id}-pg"
vault_name="openmates-${drill_id}-vault"
vault_volume="openmates-${drill_id}-vault-data"
cleanup() {
  docker rm -f "$pg_name" "$vault_name" >/dev/null 2>&1 || true
  docker volume rm "$vault_volume" >/dev/null 2>&1 || true
  rm -rf "$WORK_ROOT"
}
trap cleanup EXIT
mkdir -p "$WORK_ROOT/gnupg" "$WORK_ROOT/bundle" "$WORK_ROOT/core"
chmod 700 "$WORK_ROOT/gnupg"
started="$(date +%s)"

log "import private key from stdin"
gpg --homedir "$WORK_ROOT/gnupg" --batch --no-tty --quiet --import

load_s3_credentials
if [[ -z "$object" ]]; then
  object="$(s3 s3 cp --only-show-errors "s3://${BUCKET}/${STATE_KEY}" - |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')"
fi
log "download ${object}"
s3 s3 cp --only-show-errors "s3://${BUCKET}/${object}" "${WORK_ROOT}/backup.tar.gpg"
log "encrypted size: $(stat -c %s "${WORK_ROOT}/backup.tar.gpg") bytes"

log "decrypt and check checksums"
gpg --homedir "$WORK_ROOT/gnupg" --batch --no-tty --quiet --decrypt "${WORK_ROOT}/backup.tar.gpg" |
  tar -xf - -C "$WORK_ROOT/bundle"
rm -f "${WORK_ROOT}/backup.tar.gpg"
(cd "$WORK_ROOT/bundle" && sha256sum --quiet -c checksums.sha256)
tar -xzf "$WORK_ROOT/bundle/core.tar.gz" -C "$WORK_ROOT/core"
(cd "$WORK_ROOT/core" && sha256sum --quiet -c checksums.sha256)
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print("manifest:", m["created_at"], m["image_tag"], m["sizes"])' \
  "$WORK_ROOT/bundle/manifest.json"

log "restore Postgres into throwaway container (no network)"
pg_image="$(docker inspect -f '{{.Config.Image}}' cms-database)"
db_user="$(env_value DATABASE_USERNAME)"; db_user="${db_user:-directus}"
db_name="$(env_value DATABASE_NAME)"; db_name="${db_name:-directus}"
pg_password="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
printf '%s' "$pg_password" > "$WORK_ROOT/pg_password"
docker run -d --name "$pg_name" --network none \
  -e POSTGRES_PASSWORD_FILE=/run/drill/pg_password -e POSTGRES_USER="$db_user" -e POSTGRES_DB="$db_name" \
  -v "$WORK_ROOT/pg_password:/run/drill/pg_password:ro" "$pg_image" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$pg_name" pg_isready -U "$db_user" -d "$db_name" >/dev/null 2>&1 && break
  sleep 2
done
docker exec -i "$pg_name" psql -q -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" \
  < "$WORK_ROOT/core/postgres.sql" > "$WORK_ROOT/psql.log" 2>&1 ||
  { tail -n 20 "$WORK_ROOT/psql.log"; exit 1; }
rm -f "$WORK_ROOT/core/postgres.sql"
count() { docker exec "$1" psql -tA -U "$db_user" -d "$db_name" -c "select count(*) from $2"; }
for table in directus_users chats messages embeds; do
  log "rows ${table}: restored $(count "$pg_name" "$table"), live now $(count cms-database "$table")"
done

log "start throwaway Vault from snapshot (no network)"
mkdir -p "$WORK_ROOT/vault"
tar -xzf "$WORK_ROOT/bundle/vault.tar.gz" -C "$WORK_ROOT/vault"
vault_image="$(docker inspect -f '{{.Config.Image}}' "$VAULT_CONTAINER")"
docker volume create "$vault_volume" >/dev/null
docker run --rm --network none -v "$vault_volume:/dst" -v "$WORK_ROOT/vault/vault-data:/src:ro" \
  --entrypoint sh "$vault_image" -c 'cp -a /src/. /dst/' >/dev/null
docker run -d --name "$vault_name" --network none --cap-add IPC_LOCK \
  -v "$vault_volume:/vault/file" -v "${INSTALL_PATH}/backend/core/vault/config:/vault/config:ro" \
  "$vault_image" vault server -config=/vault/config/vault.hcl >/dev/null
vexec() { docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$vault_name" "$@"; }
for _ in $(seq 1 30); do
  vexec vault status >/dev/null 2>&1 && break
  [[ $? -eq 2 ]] && break  # 2 = sealed but reachable
  sleep 1
done
vexec sh -c 'read -r k; vault operator unseal "$k" >/dev/null' < "$WORK_ROOT/vault/vault-setup-data/unseal.key"
vexec vault status -format=json | python3 -c 'import json,sys; s=json.load(sys.stdin); assert not s["sealed"]; print("vault unsealed, version", s["version"])'

log "decrypt one server-encrypted username from the restored database with the restored Vault"
row="$(docker exec "$pg_name" psql -tA -F ' ' -U "$db_user" -d "$db_name" -c \
  "select vault_key_id, encrypted_username from directus_users where vault_key_id is not null and encrypted_username like 'vault:%' order by date_created desc nulls last limit 1")"
key_id="${row%% *}"
ciphertext="${row#* }"
[[ -n "$key_id" && "$ciphertext" == vault:* ]]
context="$(printf '%s' "$key_id" | base64 -w0)"
{ cat "$WORK_ROOT/vault/vault-setup-data/api.token"; echo; printf '%s\n%s\n%s\n' "$key_id" "$ciphertext" "$context"; } |
  vexec sh -c 'read -r VAULT_TOKEN; export VAULT_TOKEN; read -r key; read -r ct; read -r ctx
    vault write -field=plaintext "transit/decrypt/$key" ciphertext="$ct" context="$ctx"' |
  python3 -c 'import base64,sys; p=base64.b64decode(sys.stdin.read().strip()); assert p; print("decrypt ok: username of", len(p.decode()), "characters (not shown)")'

log "restore drill passed in $(( $(date +%s) - started )) s; cleaning up"
