---
name: define-contract
description: Discover, draft, present, approve, and validate a compact permanent OpenMates contract bundle before feature specification or semantic behavior changes
user-invocable: true
argument-hint: "<feature or existing contract ID>"
---

## Workflow

1. Search `contracts/generated/registry.yml`, existing bundles, semantic pages,
   active/archived specs, tests, source surfaces, and tracker context before
   drafting. Reuse shared models and architecture assertions rather than copying.
2. Create or edit `contract.yml` plus `examples.yml` only in the active session
   worktree. Keep `contract.yml` compact; examples remain separate and are loaded
   for ambiguity and test derivation.
3. Validate with `python3 scripts/contracts.py validate <bundle>`, then run
   `python3 scripts/contracts.py generate`.
4. Generate and privately upload the exact-fingerprint approval document:

```bash
python3 scripts/sessions.py contract approval-pdf --session <session-id> --bundle <bundle> --baseline-ref HEAD
```

   Paste the returned Markdown PDF link into the chat before asking for
   approval. The PDF must contain the complete `contract.yml` and `examples.yml`;
   only changed text is colored, using inline green `+` insertions and inline red
   `-` deletions while unchanged text remains neutral. A local path or prose summary is not
   a substitute. If rendering or upload fails, repair it before asking.
5. Briefly explain affected assertions, surfaces, and evidence invalidation next
   to the embedded PDF. The PDF is the canonical review artifact; do not flood
   the chat with raw YAML unless the user asks.
6. Ask for explicit user confirmation of the fingerprint shown in the PDF and
   stop. Do not create/update the
   implementation spec or product code before the response.
7. After explicit approval, run:

```bash
python3 scripts/contracts.py approve <bundle> \
  --session <SESSION_ID> \
  --review-artifact <PDF_APPROVAL_JSON> \
  --confirmation explicit_user_confirmation
```

   Use the `Review artifact:` path printed by the PDF command. The approval CLI
   verifies that JSON receipt, the reviewed PDF hash, and the current bundle
   fingerprint before recording approval.

8. Any later bundle edit changes the fingerprint. Generate and embed a new PDF,
   then repeat presentation and approval; never reuse a stale receipt.

## Rules

- Contracts define durable truth; never modify one merely to match code or tests.
- New features and semantic changes require approval. Implementation-only work
  references an existing approved contract and refreshes evidence.
- Canonical surfaces are REST API, CLI, SDKs (npm/pip), and GUI (web/Apple).
- Do not add contract references to product source headers.
