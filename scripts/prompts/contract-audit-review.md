You are reviewing the latest deterministic OpenMates contract-audit report and turning it into actionable next-step recommendations.

**Date:** {{DATE}} | **HEAD:** {{GIT_SHA}}

## Inputs

Read this JSON report first:

`{{REPORT_PATH}}`

Summary snapshot:

```json
{{REPORT_SUMMARY}}
```

Recent commits for prioritization context:

```text
{{RECENT_COMMITS}}
```

## Task

Produce the top 10 recommended next steps from the contract-audit findings.

Focus on recommendations that reduce repeated bugs, reduce repeated code, or enforce project architecture rules. Group repeated findings by root cause instead of listing every file individually.

## Constraints

- This is a read-only recommendation session.
- Do not edit files, commit, deploy, install dependencies, or run destructive commands.
- Do not recommend immediate auto-fixing for high-risk encryption findings unless the report makes the safe refactor obvious.
- Prefer small, deterministic follow-up tasks that can be verified with lint or targeted tests.
- If a rule appears noisy, recommend rule tuning or allowlisting before implementation.

## Output

Use this structure:

1. Top 10 recommendations, ordered by impact and confidence.
2. For each recommendation include: root cause, representative findings, expected impact, risk, verification command, and whether it is safe for future auto-fix.
3. Separate “do not auto-fix yet” findings.
4. Suggested next implementation batch: at most 3 tasks.
