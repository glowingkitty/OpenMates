---
name: backfill-contract
description: Incrementally map a touched legacy test or spec cluster to existing contract assertions, drafting a new compact contract only when no approved contract applies
user-invocable: true
argument-hint: "<test path or spec cluster>"
---

## Workflow

1. Run `python3 scripts/contracts.py check-test <path>` and inspect the generated
   registry before creating anything.
2. Search existing specs, neighboring tests, architecture docs, app metadata,
   REST/CLI/SDK/GUI surfaces, and relevant code to identify the actual feature.
3. If approved assertions apply, add per-test `contract-test` metadata with proof
   strength and surface, then regenerate the assertion index.
4. If no approved contract defines the intended behavior, extract stable truth
   from the whole feature/spec cluster, not only one test. Separate historical
   implementation choices from durable behavior.
5. Invoke `define-contract`, present the complete compact contract, and wait for
   approval before mapping the test or changing implementation behavior.
6. Update the existing full spec with contract references and evidence locations;
   do not replace its discovery, tasks, attempts, handoff, or evidence ledger.
7. Run `python3 scripts/contracts.py generate` and
   `python3 scripts/contracts.py check-generated` before deploy.

## Rules

- Never infer that an existing passing test is approved product truth.
- Search before creating; avoid one permanent contract per historical spec.
- Touched legacy tests may not remain `legacy_unmapped` at deploy.
