# SEO Audit — {{DATE}}

You are running a read-only SEO optimization review for OpenMates.

## Operating Rules

- Do not edit files, commit, deploy, or start other sessions.
- The current production site and current codebase are both required inputs.
- Recent commits are prioritization context only; verify findings against live HTTP responses and current source files.
- HTTP checks must be safe GET/HEAD requests only. Use a 15 second timeout.

## Context

- Date: {{DATE}}
- HEAD: {{GIT_SHA}}
- Recent context window: {{RECENT_SINCE}}

## Current Codebase Inventory

{{CODEBASE_INVENTORY}}

## Recent SEO-Relevant Git Context

```text
{{RECENT_CHANGES}}
```

## Required Production Checks

Use `curl` or equivalent safe HTTP requests against `https://openmates.org`:

- `/sitemap.xml`
- `/robots.txt`
- `/`
- `/intro/for-everyone`
- `/example` if available
- One example/demo chat page from the sitemap
- `/docs`
- `/docs/api`
- One docs subpage from the sitemap
- The OG image URL referenced by representative pages

## Required Source Inspection

Inspect current files from:

- `.opencode/agents/seo-auditor.md`
- `frontend/apps/web_app/src/app.html`
- `frontend/apps/web_app/src/routes/**`
- `frontend/packages/ui/src/i18n/sources/metadata/**`
- `frontend/packages/ui/src/demo_chats/**`
- `scripts/_daily_meeting_helper.py`

## Review Goals

Find the top SEO optimization suggestions beyond the daily smoke check.

## Checks

- Sitemap coverage, duplicate URLs, missing important URLs, and suspicious `lastmod` patterns.
- HTTP status for representative sitemap pages.
- SSR/prerender status for indexable routes.
- Missing, duplicated, or low-quality title/description/canonical tags.
- OG/Twitter tag completeness and OG image reachability.
- JSON-LD presence and validity where applicable.
- i18n key leaks in metadata.
- Hreflang and multilingual SEO gaps.
- Internal link opportunities between homepage, intro, examples, docs, and demo chats.
- Recent SEO-sensitive code changes that need follow-up.

## Output Format

```markdown
# SEO Audit — {{DATE}}

## Score: X/100

## Critical / High Priority
| # | Priority | Issue | Page(s) | Evidence | Suggested Fix | File |
|---|----------|-------|---------|----------|---------------|------|

## Medium Priority
- ...

## Meta Coverage Matrix
| Page | title | desc | canonical | og | twitter | JSON-LD | robots |
|------|-------|------|-----------|----|---------|---------|--------|

## Internal Linking Opportunities
- ...

## What Looks Good
- ...
```

Keep the report to the top 10 actionable SEO recommendations. Include exact file paths and, where possible, line references.
