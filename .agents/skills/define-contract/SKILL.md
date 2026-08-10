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
4. For a new contract, quote the complete `contract.yml` in chat and summarize
   every examples group. For an existing contract, quote every explicit
   `contract.yml` and `examples.yml` change. Explain affected assertions,
   surfaces, and evidence invalidation.
5. Ask for explicit user confirmation and stop. Do not create/update the
   implementation spec or product code before the response.
6. After explicit approval, run:

```bash
python3 scripts/contracts.py approve <bundle> \
  --session <SESSION_ID> \
  --confirmation explicit_user_confirmation
```

7. Any later bundle edit changes the fingerprint. Repeat presentation and
   approval; never reuse a stale receipt.

## Rules

- Contracts define durable truth; never modify one merely to match code or tests.
- New features and semantic changes require approval. Implementation-only work
  references an existing approved contract and refreshes evidence.
- Canonical surfaces are REST API, CLI, SDKs (npm/pip), and GUI (web/Apple).
- Do not add contract references to product source headers.
