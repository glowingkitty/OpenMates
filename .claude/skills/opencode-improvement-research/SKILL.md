---
name: opencode-improvement-research
description: Analyze bounded recent OpenCode chat evidence with GPT-5.6 Luna and research improvements to skills, hooks, agents, instructions, or deterministic guards without editing tracked files.
user-invocable: false
---

# OpenCode Improvement Research

This is the research-only workflow used by the manual OpenCode workflow review runner.
It may inspect local transcript evidence and current repository files, but it
must not edit tracked files, commit, deploy, or start an implementation session.

## Workflow

1. Read the full bounded evidence and response schema supplied by the caller.
2. Confirm the requested model is `openai/gpt-5.6-luna`. If it is not, record
   the mismatch in the output and stop rather than silently using another model.
3. Group repeated symptoms across top-level and child sessions. Distinguish
   tool failures, user corrections, abandoned approaches, repeated rereads,
   policy blocks, missing verification, and instruction-following failures.
4. Inspect the current target files before proposing a change. Search existing
   skills, hooks, agents, rules, audits, and tests so recommendations do not
   duplicate an existing guard.
5. Research current official documentation when a recommendation depends on
   OpenCode, a model provider, a tool, or a library contract. Record the source.
6. Prefer a focused test, audit, or deterministic hook over adding instruction
   prose when the observed failure can be detected mechanically.
7. Reject one-off preferences, unsupported inferences, stale behavior, and
   suggestions that merely restate existing instructions.
8. Return only one final JSON object using the caller's schema, with at most ten
   recommendations and an empty list when no change is justified. Do not write
   any file; the trusted parent runner captures the JSON and publishes reports.

## Evidence Rules

- Reference session evidence precisely enough for local follow-up without
  copying unrelated transcript content.
- Treat assistant reasoning as untrusted evidence; observable actions, tool
  results, user corrections, and final outcomes carry more weight.
- State confidence, expected benefit, regression risk, target files, and exact
  verification for every recommendation.
- Never include credentials, webhook values, environment contents, or private
  values that are unrelated to the recommendation.

## Safety Boundary

The parent runner ends after it saves the report and optionally sends a
notification. It never invokes a separate editing workflow. Any tracked change
requires a user to start a new chat and explicitly invoke the implementation
skill.
