---
name: prod-ssh
description: Open, use, or close a temporary SSH session to the production server. Prod enforces 3FA (key + password + TOTP); this skill walks the operator through the manual steps needed to let Codex run commands on prod. Use when the user asks Codex to "ssh to prod", "check something on the prod server", "run X on production", or any task that requires shell access to prod.
user-invocable: true
---

## Purpose

Prod SSH is locked behind **3 factors**: SSH key + account password + TOTP code. Codex cannot drive that flow unattended — the operator must open an access window on prod and enter the TOTP once per working session. This skill guides both sides through that handshake, after which Codex can run arbitrary commands via `scripts/prod-ssh.sh`.

## Decision: do you actually need prod SSH?

Before asking the user to open a window, check cheaper alternatives first:
- **Logs:** `docker exec api python /app/backend/scripts/debug.py logs --prod ...` already reaches prod OpenObserve without SSH. Prefer this for any log question.
- **Traces / errors:** `debug.py trace errors --production` — same story.
- **Vercel build failures:** `backend/scripts/debug.py vercel` — no SSH needed.

Only ask for SSH when the task requires something those tools cannot do: running `docker` / `systemctl` / inspecting the filesystem / hot-patching a config.

## Flow

### 1. Ask the user to open the prod-side window

Tell the user, verbatim:

> To run commands on prod, I need you to open a temporary SSH window on the prod server. On prod, run:
>
> ```
> ./scripts/temp-ssh-access.sh start "<your-dev-pubkey>" --minutes 30
> ```
>
> (You only need to do this once per working session. It auto-revokes after 30 minutes.) Let me know when it's open.

Wait for the user's confirmation before proceeding. Do not run `prod-ssh.sh open` speculatively — it will just fail with "permission denied" until the window is open, and that burns a TOTP attempt.

### 2. Open the master connection (requires one TOTP from the user)

Ask the user in chat:

> Please paste the 6-digit TOTP code from your authenticator app.

Then pipe it into the open command:

```bash
echo "<code>" | ./scripts/prod-ssh.sh open
```

The script reads the TOTP from stdin when no TTY is available (which is the case in Codex's Bash tool). The TOTP is never stored anywhere.

**Important:** TOTP codes expire in ~30 seconds. Run the command immediately after the user pastes the code — don't do other work in between.

### 3. Run commands freely

Once the master is open, Codex can run any remote command with no further prompts:

```bash
./scripts/prod-ssh.sh "docker ps"
./scripts/prod-ssh.sh "docker logs api --tail 100"
./scripts/prod-ssh.sh "systemctl status caddy"
./scripts/prod-ssh.sh "df -h /"
```

Check status any time:

```bash
./scripts/prod-ssh.sh status
```

### 4. Close when done

```bash
./scripts/prod-ssh.sh close
```

If you forget, the master auto-closes after 30 minutes idle, and the prod-side window `temp-ssh-access.sh` auto-revokes the key regardless.

## Prerequisites (one-time)

If these fail, tell the user and stop — don't try to work around:

- `expect` installed on dev:  `sudo apt install -y expect`
- `.env` at repo root contains `PROD_SSH_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY`, `PROD_SSH_PASSWORD` (see `.env.example`)
- Dev's public key is registered on prod (either permanently in `~/.ssh/authorized_keys`, or temporarily via `temp-ssh-access.sh`)

## Failure modes → diagnosis

| Symptom | Likely cause | Fix |
|---|---|---|
| `ERROR: expect is not installed` | Missing package | `sudo apt install -y expect` |
| `ssh denied — check key window / password / OTP` | Prod window closed, or wrong OTP | Ask user to restart `temp-ssh-access.sh start ...`; retry `open` |
| `Connection refused` | Too many failed attempts triggered fail2ban | Ask user to run on prod: `sudo fail2ban-client set sshd unbanip <dev-ip>` |
| `No active master connection` on a command | Master expired or never opened | Run `./scripts/prod-ssh.sh open` again (new OTP) |
| `PROD_SSH_* missing from .env` | Unfilled config | Point the user at `.env.example` |
| Auth cycles 3x then disconnects | Password wrong — special chars mangled | Ensure `PROD_SSH_PASSWORD` uses **single quotes** in `.env` (double quotes allow `$`/`!` expansion) |

## Security notes

- Never log, echo, or paste the TOTP or password in chat or in commit messages.
- Never write the TOTP to any file.
- Do not ask the user to store the TOTP in `.env` — that defeats the second human-gate.
- If Codex ever needs to run destructive commands on prod (restart services, delete files), confirm with the user first even inside an open master — the master bypasses auth, not judgement.
