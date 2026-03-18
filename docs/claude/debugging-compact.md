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
- **R11** App missing from store: check `/v1/health`, restart api if absent
- **R12** Vercel failures: `debug.py vercel` (never `vercel logs`)

## Where to Look First

| Problem         | Check First                               | Then                |
| --------------- | ----------------------------------------- | ------------------- |
| AI response     | `task-worker`, `app-ai-worker`            | `api` (WebSocket)   |
| Login/auth      | `api`                                     | `cms` (Directus)    |
| Payment         | `api`                                     | `task-worker`       |
| Sync/cache      | `api` (PHASE1, SYNC_CACHE)                | `cache` (Dragonfly) |
| Frontend        | OpenObserve `job='client-console'`        | Browser console     |
| Scheduled tasks | `task-scheduler`                          | `task-worker`       |
| Mobile/iPhone   | `debug.py logs --browser --device iphone` | `--level error`     |

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
