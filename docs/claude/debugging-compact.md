# Debugging Rules (Compact)

Full reference: `sessions.py context --doc debugging`

## Quick Rules

- **R0** Session mode controls context (bug=full health, feature=one-liner, docs/question=skip)
- **R1** State your understanding FIRST, ask "Is this correct?" before touching code
- **R2** Check `git log -5 -- <file>` — if not your commit, report, don't fix
- **R3** Establish: who reported it (user vs admin)? Which server (dev vs prod)?
- **R4** Production: always use `debug.py`. Dev: prefer `debug.py --o2`, fallback: `docker compose logs`
- **R5** 502/connection error: check `docker compose ps`, wait 15-30s, retry up to 3x
- **R6** Missing info: name the single most likely missing variable
- **R7** UI bugs: ask for share link first, open in Firecrawl
- **R8** Endpoint not receiving: check Caddyfile first
- **R10** Embed resolution failures: check `resolve_embed_references_in_content()` in embed_service.py
- **R11** App/skill missing from store: Two filtering layers — (1) Health: check `/v1/health` (app container down?), restart api if absent. (2) Skill availability: check `/v1/apps/metadata` vs `?include_unavailable=true` — if skills appear with the flag, the issue is provider API key filtering in `apps.py:is_skill_available()`. Check `no_api_key` flags in `app.yml` and Vault keys.
- **R12** Vercel failures: `debug.py vercel` (never `vercel logs`)
- **R13** If `debug.py issue <id>` returns "NOT FOUND" but session start's ISSUES section showed that issue as recent, the failure is a Directus 500 — not a missing record. Run `debug.py logs --o2 --since 5 --search 'directus'` to verify. A Directus query error is a blocking infrastructure problem — report it before continuing

## Where to Look First

| Problem           | Check First                               | Then                |
| ----------------- | ----------------------------------------- | ------------------- |
| AI response       | `task-worker`, `app-ai-worker`            | `api` (WebSocket)   |
| Login/auth        | `api`                                     | `cms` (Directus)    |
| Payment           | `api`                                     | `task-worker`       |
| Sync/cache        | `api` (PHASE1, SYNC_CACHE)                | `cache` (Dragonfly) |
| Frontend          | OpenObserve `job='client-console'`        | Browser console     |
| Scheduled tasks   | `task-scheduler`                          | `task-worker`       |
| Mobile/iPhone     | `debug.py logs --browser --device iphone` | `--level error`     |
| Missing app/skill | `/v1/health` + `/v1/apps/metadata`        | app.yml providers, Vault keys |

## Key Commands

```bash
debug.py logs --o2 --preset web-app-health --since 60    # Start here
debug.py logs --o2 --preset chat-processing --since 30   # Chat issues
debug.py logs --o2 --preset test-events --since 60       # Test runs
debug.py logs --browser --device iphone --level error     # Mobile
debug.py vercel                                           # Vercel failures
debug.py issue <id> --timeline                            # Issue: unified browser+backend log timeline
debug.py issue <id> --timeline --before 15 --after 5     # Custom time window (default: −10/+5 min)
debug.py issue <id> --timeline --production               # Same, against prod OpenObserve
```

## Issue Inspection

- `debug.py issue <id>` — metadata + decrypted fields + S3 YAML (IndexedDB, HTML snapshots, runtime state, action history, screenshot)
- `debug.py issue <id> --timeline` — **use this for log investigation** instead of `--full-logs`; queries OpenObserve live and merges browser console (`job=client-issue-report`) + backend container logs into one chronological view with a `── ISSUE REPORTED ──` marker
- S3 YAML no longer stores `console_logs` or `docker_compose_logs` — those are queried live via `--timeline`
