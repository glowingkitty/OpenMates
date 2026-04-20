You are scanning the OpenMates codebase for pattern inconsistencies — places where a migration or refactor was started but not completed everywhere, or where similar code uses different patterns without reason.

**Date:** {{DATE}} | **HEAD:** {{GIT_SHA}} | **Day:** {{DAY_OF_WEEK}}

## Architecture context

SvelteKit frontend, Python/FastAPI backend, PostgreSQL via Directus CMS, Docker microservices, client-side encryption, WebSocket real-time sync, Celery task queue.

## Scope

### Priority 1 — Files changed in the last 7 days (ALWAYS scan these first)

```
{{RECENT_CHANGES}}
```

### Priority 2 — Rotating sector ({{SECTOR_NAME}})

```
{{SECTOR_PATHS}}
```

## Previous findings (carry forward any that are still unresolved)

{{PREVIOUS_FINDINGS}}

## What to look for

1. **Partial migrations** — A new pattern was adopted (e.g. new encryption key system, new API wrapper, new component pattern) but old code still uses the previous approach in some files. Look for the new pattern, then search for leftover old pattern usage.
2. **Forgotten updates** — A change was made in N out of M similar places (e.g. updated error handling in 3 of 5 WebSocket handlers). Find the ones that were missed.
3. **Inconsistent design patterns** — Similar functionality implemented differently without reason (e.g. some services use class-based pattern while others use functional, some stores use `$state` while others use writable stores for the same kind of data).
4. **Old API usage** — Shared wrappers or utilities exist but some files still call the underlying API directly (e.g. raw `fetch()` where `httpx` wrapper exists, direct Directus calls where service methods exist).

## Output format

You MUST write your findings to `logs/nightly-reports/pattern-inconsistencies.json` using the Write tool. Write the file after EACH finding so partial results survive a hard kill.

The JSON structure:

```json
{
  "job": "pattern-consistency",
  "ran_at": "{{DATE}}T{{TIME}}Z",
  "status": "ok",
  "summary": "Found N pattern inconsistencies across M files",
  "details": {
    "head_sha": "{{GIT_SHA}}",
    "sector_scanned": "{{SECTOR_NAME}}",
    "items": [
      {
        "title": "Short descriptive title",
        "category": "consistency",
        "files": ["path/to/old-pattern-file.ts:42"],
        "effort": "small|medium|large",
        "impact": "low|medium|high",
        "priority_score": 7,
        "description": "What the inconsistency is",
        "suggested_fix": "Which pattern to standardize on and what to change",
        "current_pattern": "Description or code snippet of the correct/new pattern",
        "old_pattern": "Description or code snippet of the outdated pattern",
        "instances_using_old": ["file1.ts:10", "file2.py:25"],
        "days_pending": 0
      }
    ]
  }
}
```

## Rules

1. **Verify by reading code.** Never report issues based on filenames alone. Read the actual implementations to confirm the inconsistency.
2. **Top 5 only.** Report at most 5 items, ranked by priority_score (0-10, where 10 = highest priority). Priority = number of affected files × risk of bugs from inconsistency.
3. **Carry forward.** Items from "Previous findings" that are still present in the code should be included with `days_pending` incremented by 1. If the inconsistency was resolved, drop it.
4. **Show both patterns.** Always include `current_pattern` and `old_pattern` with actual code snippets so the developer can see exactly what needs to change.
5. **List all instances.** `instances_using_old` must list every file:line that still uses the old pattern (up to 20 instances).
6. **Write incrementally.** After discovering each finding, update the JSON file with all findings so far. This ensures partial results survive a hard kill.
7. **25-minute soft limit.** If you've been running for approximately 25 minutes, STOP scanning and summarize whatever you've found so far. Write the final JSON and finish.
8. **Small = <30 min fix, Medium = 1-3 hours, Large = half day or more.**
