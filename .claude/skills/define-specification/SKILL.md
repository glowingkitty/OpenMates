---
name: define-specification
description: Discover, draft, present, approve, and validate a compact permanent OpenMates Specification before feature planning or semantic behavior changes
user-invocable: true
argument-hint: "<feature or existing specification ID>"
---

## Workflow

1. Search `specifications/generated/registry.yml`, existing Specifications,
   semantic pages, Plans, tests, source surfaces, and tracker context before
   drafting. Prefer extending an existing Specification for the owning feature,
   app skill, or shared behavior before creating a separate bundle. Record the
   closest existing contracts and why they cannot cover the behavior when a new
   bundle is necessary. Reuse shared models and architecture assertions rather
   than copying; individual focus-mode contracts reference the shared lifecycle.
2. Create or edit `specification.yml` plus `examples.yml` only in the active
   session worktree. Keep `specification.yml` compact; examples remain separate
   and are loaded for ambiguity and test derivation. Every new or changed
   requirement/assertion must have one or two concrete examples in `examples.yml`
   with an explicit assertion ID mapping, realistic inputs or state, the action,
   and observable expected behavior. Reuse and update suitable examples where
   possible. Check coverage against the changed assertions before validation;
   an unrelated example elsewhere in the bundle does not satisfy this rule.
3. Validate with `python3 scripts/specifications.py validate <bundle>`, then run
   `python3 scripts/specifications.py generate`.
4. Generate and privately upload the exact-fingerprint approval document:

   ```bash
   python3 scripts/sessions.py specification approval-pdf --session <session-id> --bundle <bundle> --baseline-ref HEAD
   ```

   Paste the returned Markdown PDF link into the chat before asking for approval.
   The PDF must contain the complete `specification.yml` and `examples.yml`.
   Before asking for approval, verify that the review artifact shows changed text using inline green `+`
   insertions and inline red `-` deletions while unchanged text stays neutral.
5. Briefly explain affected assertions, surfaces, and evidence invalidation next
   to the embedded PDF. Ask for explicit user confirmation of its fingerprint and
   stop. Do not create/update a Plan or product code before the response.
6. After explicit approval, run:

   ```bash
   python3 scripts/specifications.py approve <bundle> \
     --session <SESSION_ID> \
     --review-artifact <PDF_APPROVAL_JSON> \
     --confirmation explicit_user_confirmation
   ```

7. Any later Specification edit changes the fingerprint. Generate and embed a
   new PDF, then repeat presentation and approval; never reuse a stale receipt.

## Rules

- Specifications define durable truth; never modify one merely to match code or tests.
- Describe observable agent behavior in the owning product contract when it is a
  promised outcome; keep prompt wording and implementation tactics in the app's
  instruction sources. Backfilling documents current behavior without treating
  known defects as approved truth.
- New features and semantic changes require approval. Implementation-only work
  references an existing approved Specification and refreshes evidence.
- Canonical surfaces are REST API, CLI, SDKs (npm/pip), and GUI (web/Apple).
- Do not add Specification references to product source headers.
