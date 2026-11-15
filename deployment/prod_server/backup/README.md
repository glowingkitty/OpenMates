# Nightly production backup

First line of defence for the production core server (TASK-5693, owner decision
of 15 Nov 2026). A copy at a different provider is out of scope for now
(review planned for 15 Dec 2026).

## What is backed up

One encrypted file per night, `openmates-prod-<UTC timestamp>.tar.gpg`, holding:

| Part | Content |
|---|---|
| `core.tar.gz` | `openmates server backup`: full Postgres dump (`pg_dump --clean`), runtime `.env`, runtime `config/` |
| `vault.tar.gz` | Vault file storage (`openmates-vault-data`) and vault-setup data (`openmates-vault-setup-data`: `unseal.key`, `api.token`) |
| `manifest.json`, `checksums.sha256` | Creation time, image tag, sizes, SHA-256 of both parts |

Vault is paused (`docker pause`) only while its volume is copied, so the
snapshot is consistent. `after-run` unpauses it on every exit path.

User uploads already live in object storage and are not part of this backup.

## Encryption and keys

- The backup is encrypted on prod **before** upload with GnuPG (Curve25519) to
  one public key. Prod keeps only the public key
  (`~/.config/openmates-backup/recipient.asc`), so the nightly job cannot read
  older backups.
- The private key is stored in prod Vault at `kv/providers/prod_backup`
  (field `gpg_private_key_b64`, base64 of the armored key), imported the
  standard way through `SECRET__PROD_BACKUP__GPG_PRIVATE_KEY_B64` in the
  runtime `.env` and vault-setup.
- Recovery copy for the owner, reachable without prod: on the dev server in
  `/home/superdev/.config/openmates-prod-backup-recovery/` (mode 700; private
  key, public key, fingerprint). The owner should also keep it in a password
  manager. Anyone with this key and the object storage keys can read every
  backup.

## Storage, retention, size

- Hetzner Object Storage, dedicated bucket (name and location in
  `~/.config/openmates-backup/backup.env` on prod), prefix `prod/nightly/`.
  `prod/state/latest.json` names the newest verified copy.
- The job keeps the newest 7 copies and deletes older ones, but only after a
  new copy was uploaded and its size verified. A stalled job therefore never
  ages out the last good backups. Incomplete multipart uploads expire after
  one day (bucket lifecycle rule).

## Schedule and alerts

| Unit | When | Alert |
|---|---|---|
| `openmates-prod-backup.timer` | 02:30 UTC daily (+ up to 10 min) | Discord on any failed, killed or timed-out run (`ExecStopPost`) |
| `openmates-prod-backup-watchdog.timer` | hourly | Discord when the last verified upload is older than 26 h; repeats every 24 h |

Both use the production runtime-health Discord webhook from the runtime `.env`
(`OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION`).

## Install or update on prod

```bash
mkdir -p ~/openmates-backup ~/.config/openmates-backup
cp deployment/prod_server/backup/*.sh ~/openmates-backup/   # from a checkout or via scp
cp backup.env.example ~/.config/openmates-backup/backup.env  # fill bucket/region, chmod 600
cp <public key> ~/.config/openmates-backup/recipient.asc
sudo cp deployment/prod_server/backup/systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openmates-prod-backup.timer openmates-prod-backup-watchdog.timer
```

Run one backup now: `sudo systemctl start openmates-prod-backup.service`, then
`journalctl -u openmates-prod-backup.service -n 50`.

## Restore

The restore drill is the restore procedure, minus the switch-over:

```bash
./scripts/prod-ssh.sh "~/openmates-backup/openmates-prod-backup-restore-drill.sh --key-stdin" \
  < /home/superdev/.config/openmates-prod-backup-recovery/prod-backup-private-key.asc
```

It downloads the newest copy, decrypts it, checks all checksums, restores
Postgres and Vault into throwaway containers without network, unseals that
Vault with the restored unseal key, and decrypts one server-encrypted username
from the restored database with the restored Vault (prints only its length).
Everything it creates is removed at the end.

For a real recovery, decrypt the same way, then on the target server:
`openmates server restore --file core.tar.gz` (database, `.env`, config), and
replace the contents of the `openmates-vault-data` and
`openmates-vault-setup-data` volumes with `vault.tar.gz` before starting Vault.
