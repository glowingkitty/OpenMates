#!/usr/bin/env bash
# Nightly OpenMates production backup (first line of defence, TASK-5693).
#
# What one run does, in order:
#   1. `openmates server backup`: Postgres dump + runtime .env + config
#      (the same archive the CLI makes before every update).
#   2. Vault snapshot: the Vault file-storage volume plus the vault-setup volume
#      (unseal key and service token). Vault is paused for the copy so the
#      snapshot is consistent; it is always unpaused, also on failure.
#   3. Bundle both with a manifest and encrypt it on this host with the backup
#      public key (GnuPG). Only the public key lives on prod as a file; the
#      private key is in prod Vault and in an off-prod recovery copy.
#   4. Upload to Hetzner Object Storage, verify the stored size, write
#      state/latest.json, then delete all but the newest $KEEP_COPIES copies.
#
# Failure alerts are sent by the `after-run` subcommand, which systemd runs as
# ExecStopPost, so a crash, kill or timeout alerts too. The separate watchdog
# (openmates-prod-backup-watchdog.sh) alerts when no run succeeded for 26 h.
#
# Secrets: S3 keys are read from prod Vault at run time and exist only in this
# process's environment; the Discord webhook comes from the runtime .env.
# Nothing secret is printed. Setup and restore: README.md next to this file.
set -Eeuo pipefail
umask 077

# shellcheck source=openmates-prod-backup-lib.sh
source "$(dirname "$(readlink -f "$0")")/openmates-prod-backup-lib.sh"

run_backup() {
  require_storage_settings
  mkdir -p "$STATE_DIR"
  exec 9>"${STATE_DIR}/run.lock"
  flock -n 9 || { log "another backup run holds the lock"; exit 75; }
  rm -f "${STATE_DIR}/current-step"

  local stamp name work
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  name="openmates-prod-${stamp}.tar.gpg"
  work="${WORK_ROOT}/${stamp}"
  rm -rf "$WORK_ROOT"
  mkdir -p "$work"
  trap 'unpause_vault; rm -rf "$WORK_ROOT"' EXIT

  step "check recipient key"
  [[ -s "$RECIPIENT_FILE" ]]

  step "database and runtime archive"
  openmates server backup --path "$INSTALL_PATH" --output "${work}/core.tar.gz" --json >/dev/null

  step "vault snapshot"
  local vault_image
  vault_image="$(docker inspect -f '{{.Config.Image}}' "$VAULT_CONTAINER")"
  docker pause "$VAULT_CONTAINER" >/dev/null
  timeout 300 docker run --rm --network none \
    -v openmates-vault-data:/snapshot/vault-data:ro \
    -v openmates-vault-setup-data:/snapshot/vault-setup-data:ro \
    --entrypoint tar "$vault_image" -czf - -C /snapshot . > "${work}/vault.tar.gz"
  unpause_vault

  step "manifest"
  local image_tag
  image_tag="$(env_value OPENMATES_IMAGE_TAG)"
  (cd "$work" && sha256sum core.tar.gz vault.tar.gz > checksums.sha256)
  python3 - "$work" "$stamp" "$image_tag" <<'PY'
import json, os, sys
work, stamp, image_tag = sys.argv[1:4]
sizes = {n: os.path.getsize(os.path.join(work, n)) for n in ("core.tar.gz", "vault.tar.gz")}
manifest = {
    "format": "openmates-prod-backup/1",
    "created_at": stamp,
    "image_tag": image_tag,
    "contents": {
        "core.tar.gz": "openmates server backup: postgres.sql, runtime .env, runtime config",
        "vault.tar.gz": "vault-data (Vault file storage) and vault-setup-data (unseal.key, api.token)",
    },
    "sizes": sizes,
}
with open(os.path.join(work, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
PY

  step "encrypt"
  local gnupg_home="${work}/gnupg"
  mkdir -m 700 "$gnupg_home"
  tar -cf - -C "$work" manifest.json checksums.sha256 core.tar.gz vault.tar.gz |
    gpg --homedir "$gnupg_home" --batch --no-tty --quiet --trust-model always \
      --compress-algo none --recipient-file "$RECIPIENT_FILE" --encrypt --output "${work}/${name}"
  rm -f "${work}/core.tar.gz" "${work}/vault.tar.gz"

  step "read storage credentials"
  load_s3_credentials

  step "upload"
  local size sha stored
  size="$(stat -c %s "${work}/${name}")"
  sha="$(sha256sum "${work}/${name}" | cut -d' ' -f1)"
  s3 s3 cp --only-show-errors "${work}/${name}" "s3://${BUCKET}/${PREFIX}/${name}"

  step "verify upload"
  stored="$(s3 s3api head-object --bucket "$BUCKET" --key "${PREFIX}/${name}" --query ContentLength --output text)"
  [[ "$stored" == "$size" ]]

  step "record success"
  python3 -c 'import json,sys; print(json.dumps({"key": sys.argv[1], "size": int(sys.argv[2]), "sha256": sys.argv[3], "created_at": sys.argv[4]}, indent=2))' \
    "${PREFIX}/${name}" "$size" "$sha" "$stamp" > "${work}/latest.json"
  s3 s3 cp --only-show-errors "${work}/latest.json" "s3://${BUCKET}/${STATE_KEY}"
  cp "${work}/latest.json" "${STATE_DIR}/last-success.json"

  step "prune old copies"
  # Delete only after a verified upload, and only beyond the newest copies, so a
  # stalled job never ages out the last good backups.
  local keys
  keys="$(s3 s3api list-objects-v2 --bucket "$BUCKET" --prefix "${PREFIX}/openmates-prod-" \
    --query 'Contents[].Key' --output text | tr '\t' '\n' | { grep -v '^None$' || true; } | sort)"
  local count
  count="$(printf '%s\n' "$keys" | grep -c . || true)"
  if (( count > KEEP_COPIES )); then
    printf '%s\n' "$keys" | head -n "$(( count - KEEP_COPIES ))" | while read -r old; do
      s3 s3api delete-object --bucket "$BUCKET" --key "$old" >/dev/null
      log "pruned ${old}"
    done
  fi

  rm -f "${STATE_DIR}/current-step" "${STATE_DIR}/stale-alerted-at"
  log "backup ok: ${PREFIX}/${name} (${size} bytes, ${count} copies before pruning)"
}

after_run() {
  # systemd ExecStopPost: always unpause Vault, alert on any non-success result.
  unpause_vault || true
  local result="${SERVICE_RESULT:-unknown}" exit_status="${EXIT_STATUS:-?}" failed_step
  if [[ "$result" == "success" ]]; then
    exit 0
  fi
  failed_step="$(cat "${STATE_DIR}/current-step" 2>/dev/null || echo unknown)"
  discord "🔴 **Prod backup FAILED** on $(hostname) at $(date -u +%FT%TZ): step \`${failed_step}\`, result \`${result}\`, exit \`${exit_status}\`. Details: \`journalctl -u openmates-prod-backup.service -n 100\`. The last good copy stays in object storage."
}

case "${1:-}" in
  run) run_backup ;;
  after-run) after_run ;;
  *) echo "usage: $0 run|after-run" >&2; exit 64 ;;
esac
