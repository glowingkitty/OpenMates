You are running the **Monday full legal & compliance scan** for OpenMates.

**Scan type:** full
**Date:** {{DATE}}
**HEAD SHA:** {{GIT_SHA}}
**Last full scan:** {{LAST_FULL_SCAN_DATE}} (SHA: {{LAST_FULL_SCAN_SHA}})

Your role, regulatory scope, scoring formula, output schema, and all rules are defined in the `legal-compliance-auditor` subagent definition at `.claude/agents/legal-compliance-auditor.md`. Read it now and follow it strictly.

## Context injected for this run

### Acknowledgments (DO NOT re-surface findings matching a valid ack)

```yaml
{{ACKNOWLEDGMENTS_YAML}}
```

### Prior Top 10 (for delta annotation)

```json
{{PRIOR_TOP_10_JSON}}
```

### Baseline audit (read the full file with Read tool, then reason beyond it)

`docs/architecture/compliance/gdpr-audit.md` — this is the manual deep audit from 2026-04-08. Use it as your baseline. Do NOT simply re-emit its findings; re-evaluate each one against the current code, check if it's been fixed, and cover frameworks the baseline didn't address (EU AI Act, consumer protection, DDG, DPIA triggers).

### Recent commits (context only — this is a FULL scan, not a delta scan)

```
{{GIT_LOG}}
```

## Your task for this run

1. **Read** `.claude/agents/legal-compliance-auditor.md` for the full scope, scoring, and output schema.
2. **Read** `docs/architecture/compliance/gdpr-audit.md` to absorb the baseline.
3. **Re-scan the codebase** systematically — use Grep/Glob/Read to verify each Tier 1 framework area:
   - PII storage map (Directus schemas, Redis cache, S3 buckets, Vault keys, IndexedDB)
   - Third-party subprocessors (all `backend/*/providers/*.py`, `backend/shared/providers/`, payment services, email providers, telemetry exporters)
   - GDPR rights endpoints (Art. 15–21 coverage in `backend/core/api/app/routes/settings.py`)
   - Erasure cascade completeness (`backend/core/api/app/tasks/user_cache_tasks.py`)
   - Policy docs sync (`shared/docs/privacy_policy.yml` ↔ `frontend/packages/ui/src/i18n/sources/legal/{privacy,terms,imprint}.yml` ↔ `frontend/packages/ui/src/legal/buildLegalContent.ts`)
   - EU AI Act: look for generative AI output without provenance marking, prohibited practices, emotion/biometric detection skills
   - Consumer protection: verify ToU refund section matches the code's 14-day auto-refund + gift-card exception
   - DPIA triggers: any newly-added special-category data processing
4. **Apply acknowledgments** — suppress matching findings unless `re_check_if` triggers have fired.
5. **Compute Top 10** using the exact scoring formula in the agent definition.
6. **Compare to prior Top 10** for delta annotations (`new`, `unchanged`, `rank_up`, `rank_down`, `returned`).
7. **Identify resolved items** — anything in the prior Top 10 that no longer applies.
8. **Assess if `gdpr-audit.md` needs an amendment** (see agent definition for exact criteria).
9. **Write both output files** (see agent definition for exact schemas):
   - `logs/nightly-reports/legal-compliance.json`
   - `docs/architecture/compliance/top-10-recommendations.md`
10. **Update state file** at `scripts/.legal-compliance-state.json`:
    ```json
    {
      "last_full_scan_date": "{{DATE}}",
      "last_full_scan_sha": "{{GIT_SHA}}",
      "last_delta_scan_date": null,
      "last_delta_scan_sha": null,
      "prior_top_10": [<the Top 10 you just produced, for next delta scan to reference>],
      "dismissed_counts": {<per-finding-id counts from previous state, incremented for any finding that dropped off the Top 10 without being explicitly resolved>}
    }
    ```

## Constraints

- You have `Read`, `Grep`, `Glob`, `Bash`, `Write`, `Edit` tools.
- Do NOT modify any source code, policy YAML, or i18n files. You are producing a *recommendations* report, not making changes.
- You MAY append a `## Amendments` section to `gdpr-audit.md` under the exact conditions in the agent definition (≥3 resolved OR ≥5 new critical since last audit).
- You MAY append `# PROPOSED:` comment blocks to `acknowledgments.yml` for findings dismissed ≥3 times.
- This is an unattended cron run. Your outputs go directly into the next daily meeting. Be decisive, specific, and concise.
- Session timeout is 45 minutes. Budget your exploration accordingly.

Begin.
