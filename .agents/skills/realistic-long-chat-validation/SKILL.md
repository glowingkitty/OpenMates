---
name: realistic-long-chat-validation
description: Run a realistic many-turn OpenMates CLI chat to validate Gemini routing, generated artifact quality, repeated compression checkpoints, and publish a successful run as an example chat
user-invocable: true
argument-hint: "[optional topic]"
---

## Overview

Use this skill when the user wants a realistic long-chat validation run, not a
synthetic smoke test. The workflow creates and continues a real OpenMates CLI
chat against `https://api.dev.openmates.org`, inspects every turn, validates at
least two compression checkpoints, and only then converts the successful share
link into a public example chat.

This skill intentionally costs real credits and can take a long time. There is
no max credit, token, or time cap unless the user adds one for the session.

## Product Contract

Source of truth: `docs/specs/realistic-long-chat-cli-validation/spec.yml`.

Do not run this workflow as a hidden unattended deterministic script. It is fine
to use short helper commands for inspection, checkpoint queries, or CLI command
wrapping, but the chat itself must proceed as individual OpenCode-controlled CLI
turns with response review before the next turn.

## Topic Agreement Gate

Before starting the CLI chat, ask the user to choose or confirm the long-running
topic. If no topic is supplied, suggest examples such as:

- Build a company from zero to launch: strategy, positioning, product, finance,
  hiring, operations, sales, marketing, documents, spreadsheets, and code tools.
- Plan a complex nonprofit program: grant strategy, stakeholder maps, budget,
  outreach, impact measurement, documents, sheets, and dashboards.
- Design and launch a technical product: requirements, architecture, GTM,
  pricing, onboarding docs, analytics sheets, and prototype code.

For the current default, use the company-building advisory chat unless the user
chooses another topic.

## Model Requirements

- Keep the normal chat on Gemini models.
- Prefer `google/gemini-3.5-flash-lite` as the primary model where the CLI or
  mention syntax can select it.
- Use the CLI-supported model mention when needed: `@Gemini-3.5-Flash-Lite`.
- Before counting the run as valid, verify backend logs show Gemini routing for
  normal turns and that compression uses the intended cheap Gemini Flash or
  Flash-Lite path.
- If a non-Gemini route is used unexpectedly, pause and ask whether to debug or
  continue.

## Stop And Pause Conditions

Pause immediately and report the issue if any of these occur:

- The CLI command fails or the assistant response is missing/unusable.
- A generated embed is clearly broken, missing, irrelevant, internally
  inconsistent, or nonsensical.
- Compression appears to complete but no durable checkpoint is persisted.
- The model route violates the Gemini requirement.
- The chat starts producing content that would be unsuitable for a public example.

When pausing, include the chat id, turn number, model when known, affected embed
or response, and a clear question: debug/fix now, continue anyway, or abandon
and start a better run.

## Live Chat Workflow

1. Ensure the CLI test account is logged in against `https://api.dev.openmates.org`.
2. Confirm the compression model guardrail from the spec is already green.
3. Start one real CLI chat with a natural first prompt for the approved topic.
4. Keep each message as an individual turn. Do not pack the whole transcript into
   one giant prompt.
5. Progress through many realistic subtopics. For the company-building default,
   use areas like strategy, customer discovery, positioning, product roadmap,
   pricing, finance, hiring, operations, legal/privacy, marketing, sales,
   documents, sheets, code/tooling, and launch review.
6. Ask for generated artifacts during the run, including documents, spreadsheet
   style planning, and code/tooling where naturally useful.
7. Inspect each assistant response and CLI-rendered embed before continuing.
8. After enough turns, check for the first compression checkpoint.
9. Continue the same chat with more inspected turns after the first checkpoint.
10. Check for and verify the second compression checkpoint.
11. Record sanitized evidence in the spec: chat id, checkpoint ids,
    `compressed_message_count`, `summary_token_estimate`, observed models, rough
    credit spend, and pause decisions.

## Checkpoint Verification

Use a direct DB or approved API check against the dev stack. A successful live
run must show at least two `chat_compression_checkpoints` rows for the same chat.

The evidence must prove the run compressed many individual messages across the
conversation. A single giant old message does not satisfy this skill.

## Publication Workflow

After the live chat succeeds:

1. Create a share link for the real chat.
2. Keep the share `#key=` fragment out of committed files and final public logs.
3. Use the existing `add-example-chat` workflow and
   `scripts/create-example-chat-from-share.mjs` to scaffold the example.
4. Verify the scaffolded data contains enough history for older-message UX.
5. Deploy before final verification.
6. Verify the deployed example page opens and `Show older messages` is visible
   and works.
7. Only then give the user the public example URL.

## Evidence Requirements

Update `docs/specs/realistic-long-chat-cli-validation/spec.yml` as work proceeds.
Record command, run id or manual evidence id, timestamp, subject commit, and a
short summary for each verification gate. If a bug pauses the workflow, record it
as an attempt/blocker with the next action.
