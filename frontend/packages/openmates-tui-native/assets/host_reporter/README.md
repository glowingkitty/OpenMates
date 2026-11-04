# OpenMates host reporter

Each core, upload and preview server pushes a signed, encrypted software report
to the dev collector over the private network. Nothing on the servers listens,
and the dev server holds no server credentials and never connects to a server.
Contract: `specifications/architecture/security-monitoring`
(`host-reports.private-push`, `ssh.vulnerability-and-intrusion`).

No network details are stored in this repository. Addresses and ports below are
placeholders (`<collector-private-ip>`, `<port>`, `<server-private-ip>`).

## What runs on a server

| Unit | Identity | Does |
| --- | --- | --- |
| `openmates-host-facts-privileged.service` | root, only `CAP_DAC_READ_SEARCH` + `CAP_SYS_PTRACE`, no IP sockets, read-only filesystem | Reads root-only facts (`sshd -T`, authorized_keys fingerprints, sshd/sudoers checksums, SSH logins from the journal, accounts, socket owners, `debsums`/`dpkg --verify`) and writes only sanitized JSON to `/run/openmates-host-facts/facts.json` (0600). |
| `openmates-host-reporter.service` | `DynamicUser=yes` (no login, password, shell, sudo or docker socket) | Receives the facts file, signing key and collector certificates through `LoadCredential=`, adds package/kernel/apt/image facts, signs with `ssh-keygen -Y sign -n openmates-host-report`, encrypts with `openssl cms -aes-256-gcm` to the collector certificate and POSTs over HTTPS with the collector TLS certificate pinned (`curl --cacert`). IP traffic is denied except to the collector address (install-time drop-in). |
| `openmates-host-reporter.timer` | | Daily (randomized) and 10 minutes after boot. |
| `/etc/apt/apt.conf.d/99openmates-host-report` | | Starts a report after each dpkg run. |

Why a privileged pre-step instead of capabilities on the reporter: `sshd -T`,
`/etc/sudoers*`, other users' `authorized_keys`, the SSH journal and socket
owners are root-only. Giving those read rights to the networked process would
let a compromised reporter exfiltrate any file. The split keeps the root part
offline (no IP sockets) and the networked part without privileges; the only
channel between them is a fixed, sanitized JSON file.

Fields collected: exactly `HOST_REPORT_FIELDS` in
`scripts/security_monitoring/models.py`. Login source addresses are kept inside
the encrypted report on dev only and are never rendered in notifications.
`deployed_image_digests` is read from `/var/lib/openmates/deployed-images.json`
(`{"images": {"<image>": "<sha256 digest>"}}`), written by the deploy step; the
reporter never touches the Docker socket. Until that file exists the field
carries `{"error": "deployed_images_file_missing"}`.

## Manual installation

Prod requires 3FA, so these steps are run by the operator.

1. On dev (once), configure the collector bind address in the gitignored
   repository `.env`:

   ```
   SECURITY_HOST_COLLECTOR_BIND=<collector-private-ip>:<port>
   ```

   Then generate the collector key material (kept under
   `logs/security-monitoring/collector/`, gitignored):

   ```
   python3 scripts/security_monitoring/host_collector.py init-collector
   ```

2. Copy to each server: `deployment/host_reporter/` and the two public
   certificates `logs/security-monitoring/collector/collector.crt` and
   `logs/security-monitoring/collector/tls.crt`. Then on the server:

   ```
   sudo sh deployment/host_reporter/install.sh --role core \
     --collector-url https://<collector-private-ip>:<port>/v1/host-report \
     --collector-cert collector.crt --collector-tls-cert tls.crt
   ```

   Use `--role upload` or `--role preview` on those servers. The script
   generates the host signing key at `/etc/openmates/host-reporter/host_ed25519`
   (root 0600, handed to the service via `LoadCredential=`), writes
   `/etc/openmates/host-reporter.conf`, the IP allowlist drop-in, units and apt
   hook, enables the timer, and prints a `register-host` command.

3. On dev, run the printed command:

   ```
   python3 scripts/security_monitoring/host_collector.py register-host --role core --pubkey "ssh-ed25519 AAAA..."
   ```

4. On dev, allow the servers through the firewall for the collector port on
   the private interface only, and install the collector unit:

   ```
   sed -e 's#@OPENMATES_ROOT@#<canonical-checkout>#g' -e 's#@OPERATOR_USER@#<operator-user>#g' \
     deployment/host_reporter/collector/openmates-host-collector.service \
     | sudo tee /etc/systemd/system/openmates-host-collector.service
   sudo mkdir -p /etc/systemd/system/openmates-host-collector.service.d
   printf '[Service]\nIPAddressAllow=<server-private-ip>/32\n' \
     | sudo tee /etc/systemd/system/openmates-host-collector.service.d/servers.conf
   sudo systemctl daemon-reload && sudo systemctl enable --now openmates-host-collector.service
   ```

   Add one `IPAddressAllow=` line per server.

5. On the server, send a first report and check it:

   ```
   sudo systemctl start openmates-host-reporter.service
   journalctl -u openmates-host-reporter.service -n 20
   ```

   On dev: `python3 scripts/security_monitoring/host_collector.py status`.

A dry run that prints the report instead of sending it (on the server, as root,
after the privileged step ran once):

```
sudo systemd-run --wait --pipe -p DynamicUser=yes \
  -p LoadCredential=host-facts:/run/openmates-host-facts/facts.json \
  -p LoadCredential=signing-key:/etc/openmates/host-reporter/host_ed25519 \
  python3 -I /usr/local/lib/openmates/host-reporter/openmates-host-reporter report --dry-run
```

## Key rotation and removal

- Rotate a host key: delete `/etc/openmates/host-reporter/host_ed25519`,
  re-run `install.sh`, and register the new public key (it replaces the role's
  previous key).
- Rotate the collector: `init-collector --force`, then re-run `install.sh` on
  every server with the new certificates.
- Remove: `systemctl disable --now openmates-host-reporter.timer`, delete the
  three units, the drop-in directory, the apt hook, `/etc/openmates/host-reporter*`
  and `/usr/local/lib/openmates/host-reporter`.

## Collector checks

The collector rejects (and counts by reason) bodies that are too large, fail
to decrypt, are signed by a key not in `logs/security-monitoring/allowed_signers`,
fail signature verification, claim a role other than the signer's principal or
a host id other than the signer's fingerprint, reuse a nonce, are older than
48 hours or more than 10 minutes in the future, or contain fields outside the
allowlist. Accepted reports go to
`logs/security-monitoring/hosts/<role>/latest.json` (previous kept as
`previous.json`); a role without a report for 36 hours is stale.
