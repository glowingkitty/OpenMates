---
name: update-prod-server
description: Monitor a merged production PR, wait for GitHub image builds and Vercel production deploy, then update the prod server via OpenMates CLI over prod SSH.
user-invocable: true
argument-hint: "<pr-url-or-number>"
---

# Skill: update-prod-server

## Purpose

Use this when a pull request has been accepted into `main` and production should
be updated from published GHCR images after Vercel production is live.

This skill is intentionally production-scoped. It verifies the release gates
first, opens the prod SSH master only after the user opens the temporary access
window and provides a fresh TOTP, then mutates production only through
`openmates server ...` commands.

## Required Inputs

- PR URL or number, for example `https://github.com/glowingkitty/OpenMates/pull/506`.
- User confirmation that prod-side temporary SSH access is open.
- A fresh 6-digit TOTP code, supplied immediately before `prod-ssh.sh open`.

## Workflow

### 1. Start Or Reuse A Session

If this is a mutating top-level chat and no session exists, start one:

```bash
python3 scripts/sessions.py start --mode feature --task "update production server from merged PR"
```

Keep the printed session ID for summaries. Do not create a second worktree for
the same OpenCode chat.

### 2. Resolve The Production Subject

Use GitHub to identify the merge commit and the image workflow run:

```bash
gh pr view <PR> --repo glowingkitty/OpenMates --json number,state,mergedAt,mergeCommit,headRefOid,baseRefName,title,url
gh run list --repo glowingkitty/OpenMates --branch main --limit 10 --json databaseId,name,status,conclusion,headSha,displayTitle,event,createdAt,updatedAt,url
```

Stop if the PR is not merged into `main` or if no `Publish Self-Host Images` run
exists for the merge commit SHA.

### 3. Poll Release Gates Every 30 Seconds

Poll the image build with GitHub's built-in watcher:

```bash
gh run watch <RUN_ID> --repo glowingkitty/OpenMates --interval 30 --exit-status
```

For Vercel, avoid running `vercel ls --yes` from a session worktree without
project metadata because it can auto-link/create a throwaway project. Prefer the
known production project name:

```bash
vercel ls open-mates-webapp --meta githubCommitSha=<MERGE_SHA>
vercel inspect <deployment-url>
```

Require all of these before touching prod:

- `Publish Self-Host Images` for the merge SHA is completed with conclusion `success`.
- The Vercel deployment for `open-mates-webapp` has `target production`, `status Ready`, and alias `https://openmates.org`.
- The deployment metadata matches the merge SHA when available.

### 4. Open Prod SSH Only After Gates Pass

Check whether a master connection already exists:

```bash
./scripts/prod-ssh.sh status
```

If no master is active, ask the user to open the prod-side window with the dev
public key from the configured prod SSH key:

```bash
set -euo pipefail; set +u; set -a; source .env; set +a; set -u; key="${PROD_SSH_KEY/#\~/$HOME}"; if [ -f "${key}.pub" ]; then printf '%s\n' "$(<"${key}.pub")"; else ssh-keygen -y -f "$key"; fi
```

Tell the user to run this on prod, replacing `<DEV_PUBKEY>` with the printed key:

```bash
./scripts/temp-ssh-access.sh start "<DEV_PUBKEY>" --minutes 30
```

After the user says SSH is open, ask for the TOTP code. Run the open command
immediately after the code is provided:

```bash
printf '%s\n' '<TOTP>' | ./scripts/prod-ssh.sh open
```

Never store or log the TOTP. Do not retry stale codes.

### 5. Inspect Prod Before Updating

Use only OpenMates CLI commands for runtime state changes:

```bash
./scripts/prod-ssh.sh "openmates server status --path /home/superdev/openmates --json"
./scripts/prod-ssh.sh "openmates server update --path /home/superdev/openmates --exclude webapp --dry-run"
```

Review the dry-run for:

- Mode is `image` unless the server is intentionally source-mode.
- Target tag/channel is correct, usually `main` for official-cloud prod.
- Services exclude `webapp`, because production web is served by Vercel.
- Backup is planned.
- Env preflight and Vault secret checks are understood.

If the dry-run reports missing provider secrets that are known non-core optional
provider entries, rerun with `--yes` only after stating why. Do not edit prod
secrets unless the user explicitly asks.

### 6. Update Prod

Run the backend-only update:

```bash
./scripts/prod-ssh.sh "openmates server update --path /home/superdev/openmates --exclude webapp --yes"
```

If the update fails during setup or health checks:

- Collect `openmates server logs --container <service> --tail 200`.
- Collect `openmates server status --path /home/superdev/openmates`.
- Prefer CLI rollback before raw Docker or Compose:

```bash
./scripts/prod-ssh.sh "openmates server update --path /home/superdev/openmates --exclude webapp --image-tag <LAST_HEALTHY_TAG> --yes"
```

Use raw `docker` only for read-only diagnostics. Do not use raw `docker compose`
for OpenMates runtime mutations unless the CLI lacks an equivalent and the user
approves the fallback.

### 7. Verify And Close

Run status and verify after update. Give warm-up time if containers are still
starting:

```bash
./scripts/prod-ssh.sh "openmates server status --path /home/superdev/openmates"
./scripts/prod-ssh.sh "openmates server verify --path /home/superdev/openmates --json"
```

Treat container health and `http.role_health` as the primary rollback/update
health signal. Report any remaining verifier failures as configuration or
runtime-contract gaps, not as a successful full verification.

Close the prod master connection when finished:

```bash
./scripts/prod-ssh.sh close
```

## Completion Summary

Report:

- PR number and merge SHA.
- GitHub Actions run ID and conclusion.
- Vercel deployment URL, production alias, and Ready status.
- Prod update command and final image tag or rollback tag.
- `openmates server status` result.
- `openmates server verify` result, including any remaining failed check IDs.
- Whether the SSH master was closed.
