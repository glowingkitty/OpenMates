# Test Failure Analysis Prompt

#

# Placeholders replaced by scripts/\_daily_runner_helper.py before passing to opencode:

# {{DATE}} — UTC date of the test run (YYYY-MM-DD)

# {{RUN_ID}} — unique run identifier (ISO timestamp)

# {{GIT_SHA}} — short git SHA the tests ran against

# {{GIT_BRANCH}} — git branch name

# {{FAILED_COUNT}} — number of failed tests

# {{TOTAL_COUNT}} — total number of tests

# {{FAILED_TESTS_JSON}} — JSON array of failed test objects with suite/name/error fields

You are analysing automated test failures for the OpenMates project.

## Test Run Context

- **Date:** {{DATE}}
- **Run ID:** {{RUN_ID}}
- **Git SHA:** {{GIT_SHA}} on branch `{{GIT_BRANCH}}`
- **Result:** {{FAILED_COUNT}} of {{TOTAL_COUNT}} tests failed

## Failed Tests

```json
{{FAILED_TESTS_JSON}}
```

## Your Task

1. **Diagnose each failure** — identify the most likely root cause based on the error message, test name, and suite. Cross-reference with recent git commits on `{{GIT_BRANCH}}` to see if any changes could have caused the failure.

2. **Group related failures** — if multiple tests fail for the same underlying reason, group them and explain the common cause once.

3. **Suggest concrete fixes** — for each root cause, provide a specific, actionable fix with file paths and code snippets where possible.

4. **Prioritise by impact** — flag any failures that indicate a broken critical path (auth, payment, data loss risk) at the top.

5. **Check for flakiness** — if the error looks like a timing/race condition or environment issue rather than a real regression, say so explicitly.

Be direct and concise. Skip preamble. Start with the diagnosis.
