You are scanning the OpenMates codebase for quick-win improvements — things that are easy to fix and high-value. You are NOT looking for dead code or unused imports (a separate nightly job handles that).

**Date:** {{DATE}} | **HEAD:** {{GIT_SHA}} | **Day:** {{DAY_OF_WEEK}}

## Architecture context

SvelteKit frontend, Python/FastAPI backend, PostgreSQL via Directus CMS, Docker microservices, end-to-end encryption, WebSocket real-time sync, Celery task queue.

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

## Categories to scan for

1. **Performance** — N+1 queries, missing database indexes, unnecessary re-renders, expensive operations in hot paths, large bundle imports that could be lazy-loaded, redundant API calls
2. **UX gaps** — broken links, missing error messages, accessibility issues (missing aria labels, poor keyboard navigation), missing loading states, confusing error text
3. **Security gaps** — hardcoded values that should be env vars, missing input validation, exposed debug endpoints, missing rate limiting, unsafe HTML rendering
4. **Code quality** — functions >50 lines that should be split, duplicated logic across files, missing type annotations on public APIs, inconsistent error handling patterns

**Do NOT report:** dead code, unused imports, unused variables, missing tests (covered by other jobs).

## Output format

You MUST write your findings to `logs/nightly-reports/quick-wins.json` using the Write tool. Write the file after EACH finding so partial results survive a hard kill.

The JSON structure:

```json
{
  "job": "quick-wins",
  "ran_at": "{{DATE}}T{{TIME}}Z",
  "status": "ok",
  "summary": "Found N quick wins across M files",
  "details": {
    "head_sha": "{{GIT_SHA}}",
    "sector_scanned": "{{SECTOR_NAME}}",
    "items": [
      {
        "title": "Short descriptive title",
        "category": "performance|ux|security|code-quality",
        "files": ["path/to/file.ts:42"],
        "effort": "small|medium|large",
        "impact": "low|medium|high",
        "priority_score": 8,
        "description": "What the issue is and why it matters",
        "suggested_fix": "Concrete suggestion for how to fix it",
        "days_pending": 0
      }
    ]
  }
}
```

## Rules

1. **Verify by reading code.** Never report issues based on filenames alone.
2. **Top 5 only.** Report at most 5 items, ranked by priority_score (0-10, where 10 = highest priority). Priority = impact × ease of fix.
3. **Carry forward.** Items from "Previous findings" that are still present in the code should be included with `days_pending` incremented by 1. If the issue was fixed, drop it.
4. **Be specific.** Include exact file:line references and short code snippets (max 5 lines).
5. **Write incrementally.** After discovering each finding, update the JSON file with all findings so far. This ensures partial results survive a hard kill.
6. **25-minute soft limit.** If you've been running for approximately 25 minutes, STOP scanning and summarize whatever you've found so far. Write the final JSON and finish.
7. **Small = <30 min fix, Medium = 1-3 hours, Large = half day or more.**
