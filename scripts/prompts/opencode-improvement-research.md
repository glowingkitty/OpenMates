# Daily OpenCode Improvement Research

Use the `opencode-improvement-research` skill. Analyze the bounded local
OpenCode evidence below for the interval `{{PERIOD_START}}` through
`{{PERIOD_END}}` at subject commit `{{SUBJECT_COMMIT}}`.

Research current repository files before recommending changes. When a finding
depends on OpenCode or another external tool's behavior, consult current
official documentation. Distinguish observed transcript evidence from inference,
deduplicate repeated symptoms, and prefer a deterministic guard or focused test
over adding more prose. Do not start subagents. Do not edit tracked files,
commit, deploy, or invoke any implementation workflow.

Return one valid JSON object as the final response with this shape:

```json
{
  "summary": "Concise assessment of the last 24 hours",
  "recommendations": [
    {
      "id": "REC-1",
      "priority": "high|medium|low",
      "category": "skill|hook|agent|instruction|deterministic_guard|no_change",
      "title": "Short title",
      "evidence": "Observed sessions, repeated behavior, and why it matters",
      "current_behavior": "What currently happens",
      "proposed_change": "Specific bounded change",
      "target_files": ["repository/relative/path"],
      "expected_benefit": "Measurable or observable improvement",
      "risk": "Regression or overfitting risk",
      "research_sources": ["official documentation or repository source"],
      "verification": ["exact focused command"]
    }
  ]
}
```

Return at most ten recommendations. Use an empty recommendation list when no
change is justified. Never include credentials or webhook values. Do not write
any file; the trusted parent runner captures the final JSON and publishes the
gitignored report.

## Bounded Local Evidence

```json
{{TRANSCRIPT_EVIDENCE}}
```
