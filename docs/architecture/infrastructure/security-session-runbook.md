# Security session runbook (one ~30-minute session)

Goal: every server reports its software state to dev, installs OS security
updates automatically, and reboots only when an update requires it.
Contracts: `deployment/host_reporter/README.md`, `deployment/os_maintenance/`.
Placeholders: `<collector-private-ip>`, `<port>` (>= 1024), `<server-private-ip>`,
`<checkout>` (canonical dev checkout), `<bundle>` (a folder with the files below).

Windows (Europe/Berlin): preview 03:30 daily, upload 03:45 daily, dev 04:00
daily (retries every 15 min until 06:00 while tests run), production Sundays
04:30. Reboot happens only if `/var/run/reboot-required` exists.

## A. Dev (prepare, no root)

1. Set the bind address in `<checkout>/.env`: `SECURITY_HOST_COLLECTOR_BIND=<collector-private-ip>:<port>`
2. `python3 scripts/security_monitoring/host_collector.py init-collector`
3. Build the bundle: `mkdir <bundle> && cp -r deployment/host_reporter deployment/os_maintenance <bundle>/ && cp logs/security-monitoring/collector/collector.crt logs/security-monitoring/collector/tls.crt <bundle>/`
4. User-level collector (no root):
   `mkdir -p ~/.config/systemd/user && sed 's#@OPENMATES_ROOT@#<checkout>#g' deployment/host_reporter/collector/openmates-host-collector.user.service > ~/.config/systemd/user/openmates-host-collector.service && systemctl --user daemon-reload && systemctl --user enable --now openmates-host-collector.service`
   Keep it running after logout: `loginctl enable-linger $USER` (root step 12 if refused).
5. Check: `systemctl --user status openmates-host-collector.service` and
   `python3 scripts/security_monitoring/host_collector.py status`.

## B. Each server (production login), repeat for core, upload, preview

Role = `core` (production), `upload`, `preview`. Run on the server as root/sudo:

6. Copy `<bundle>` to the server, `cd <bundle>`.
7. Reporter:
   `sudo sh host_reporter/install.sh --role <role> --collector-url https://<collector-private-ip>:<port>/v1/host-report --collector-cert collector.crt --collector-tls-cert tls.crt`
   It prints a `register-host` command with the public key. Copy it.
8. OS updates and reboot window:
   `sudo sh os_maintenance/install.sh --role <role>`
   then `openmates-reboot-if-required --status` and `systemctl list-timers openmates-reboot.timer`
   (the NEXT column must show the window above in Europe/Berlin).
9. If a reboot is already pending, do nothing: it happens in the window. Check: `openmates-reboot-if-required --dry-run`.
10. Send the first report: `sudo systemctl start openmates-host-reporter.service && journalctl -u openmates-host-reporter.service -n 20`
11. On dev, run the printed command (shape):
    `python3 scripts/security_monitoring/host_collector.py register-host --role <role> --pubkey "ssh-ed25519 AAAA..."`
    Then repeat step 10 on the server (the first report is rejected until registered) and on dev run
    `python3 scripts/security_monitoring/host_collector.py status`: the role must show a fresh report.

## C. Dev (the one sudo step)

12. `sudo sh deployment/os_maintenance/install.sh --role dev` (also run `sudo loginctl enable-linger <operator-user>` if step 4 needs it).
13. Firewall: allow the collector port from each server on the private interface only, for example
    `sudo ufw allow in on <private-interface> from <server-private-ip> to <collector-private-ip> port <port> proto tcp`
    (one rule per server). Do not open it on the public interface.
    (Alternative: system-level unit with `IPAddressAllow=<server-private-ip>/32`, see the reporter README.)
14. Dev has a reboot pending: it reboots at the next 04:00 window if no tests run. Hold it with
    `touch ~/.openmates/no-reboot` (remove the file to release). Status: `openmates-reboot-if-required --status`.
15. After any reboot, each host sends a report 10 minutes after boot; dev confirms the host is back
    (`host_collector.py status`). Reboot log: `/var/log/openmates-reboot.log`.

## D. Verify the CMS (Directus) is not public (1 minute, on production)

16. `sudo ss -ltnp | grep -E ':(8055)\b'` must show `127.0.0.1`, a private address or a docker bridge, never `0.0.0.0` or `[::]` on a public interface.
17. From outside the private network: `curl -m 5 -sS -o /dev/null -w '%{http_code}\n' http://<production-public-address>:8055/server/ping`
    must fail or time out. If it answers, close the port in the firewall and tell dev.

## E. Exploited-flaw (KEV) reboot

Production does not wait for Sunday. The dev monitor sends you one question push ("Reboot production
before Sunday ...?"); only after you approve, on the server: `sudo openmates-reboot-if-required --now`
(reboots only if an update requires it; ignores the dev test hold). Without an answer it reboots on Sunday 04:30.

## F. Fewer secrets within reach of dev chats (optional, 10 minutes)

Already done without root: chats can no longer read or print SSH private keys, cloud, GitHub, Claude,
Docker or Vault token files (Read denies in `.claude/settings.json`, Bash guard), and 89 old agent logs
that contained key-like strings were moved out of the repository into a private 0700 folder under
`~/.local/share/openmates-quarantine/` (delete it after a week if nothing is missing).
Needs you:

18. Production SSH: give the dev user's production key a passphrase or replace it with a dedicated key
    whose `authorized_keys` entry on production is restricted (`from=<collector-private-ip>`,
    `no-port-forwarding`, `no-agent-forwarding`). The current key on dev has no passphrase.
19. GitHub: replace the dev CLI token with a fine-grained token limited to the OpenMates repositories
    (contents, pull requests, actions read; no admin, no org scope).
20. Remove cloud credentials on dev that no current job uses (check `~/.aws/` first).
21. Later (needs a compose change): move container-only keys from the shared `.env` into a
    compose `env_file` that worktrees do not receive.

