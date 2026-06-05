# Weekly Technical Debt Analysis — {{DATE}}

You are running inside OpenMates as a read-only planning job. Do not edit files,
do not commit, and do not deploy.

## Inputs

- JSON report: `{{JSON_REPORT_PATH}}`
- Markdown report: `{{MARKDOWN_REPORT_PATH}}`

The report includes current static hotspots, six-month churn hotspots,
duplication fingerprints, test coverage proximity, and deltas versus the prior
weekly run when available.

## Required Output

Produce a concise but actionable top-five improvement plan. For each item:

- State the concrete target files or directories.
- Explain why it is in the top five, using static risk, churn, duplication, and
  previous-run delta evidence.
- Recommend the smallest safe first change.
- List verification required before and after the change.
- Call out whether the item is cleanup, refactor, test coverage, architecture,
  or guardrail work.

Prioritize work that reduces future regression risk, AI-generated boilerplate,
large-file maintainability risk, and repeated bug-fix churn. Do not recommend a
rewrite unless the report proves incremental extraction is riskier than a staged
replacement.

## Report Summary JSON

```json
{{REPORT_SUMMARY_JSON}}
```

## Markdown Report Excerpt

{{REPORT_MARKDOWN}}
