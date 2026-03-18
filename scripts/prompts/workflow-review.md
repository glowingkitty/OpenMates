You are reviewing yesterday's Claude Code (opencode) sessions to extract concrete improvement suggestions for the OpenMates developer workflow tools.

**Date:** {{DATE}} | **Reviewing sessions from:** {{YESTERDAY}}
**Previous suggestions (already captured — do not repeat):** {{LAST_SUMMARY}}

## Yesterday's Session Digests

The following are summaries of Claude Code sessions from {{YESTERDAY}} that are relevant to the workflow tooling. Each digest contains:

- The user's initial request and key back-and-forth messages
- The `sessions.py start` output header (what context Claude received)
- Any `sessions.py deploy` or `debug.py` calls and their outputs
- The final task summary

{{SESSION_DIGESTS}}

---

## Your task

Analyze the session digests above and identify **up to 10 concrete improvements** for:

- `scripts/sessions.py` — the session lifecycle manager
- `backend/scripts/debug.py` and its sub-modules (`debug_chat.py`, `debug_logs.py`, etc.)
- `CLAUDE.md` — the top-level AI assistant instruction file
- `docs/claude/*.md` — instruction docs loaded by sessions.py

Focus on:

1. **Missing context** — Claude had to ask for info that sessions.py/debug.py could have provided automatically
2. **Confusing output** — Claude misread or ignored a section of sessions.py output
3. **Missing commands** — Claude ran manual workarounds for something that should be a first-class sessions.py/debug.py subcommand
4. **Broken rules** — Claude violated a CLAUDE.md rule that could be made clearer or enforced differently
5. **Friction patterns** — Recurring multi-step sequences that could be collapsed into one command
6. **Missing flags** — A common `--flag` pattern Claude used that isn't documented

For each suggestion:

- **File:** `sessions.py` | `debug.py` | `CLAUDE.md` | `docs/claude/<name>.md`
- **Observed friction:** What happened in the session (quote or paraphrase briefly)
- **Suggestion:** Specific, actionable change (a new flag, a rule rewrite, a new subcommand, etc.)
- **Priority:** High / Medium / Low

Do NOT implement anything. Output a numbered list only. Be specific — "add error handling" is not a suggestion. "Add a `--since-last-deploy` flag to `sessions.py start` that shows commits since the last `deploy` call" is a suggestion.
