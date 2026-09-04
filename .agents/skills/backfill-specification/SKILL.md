---
name: backfill-specification
description: Incrementally map a touched legacy test or Plan cluster to approved Specification assertions, drafting a new compact Specification only when none applies
user-invocable: true
argument-hint: "<test path or Plan cluster>"
---

## Workflow

1. Run `python3 scripts/specifications.py check-test <path>` and inspect the
   generated registry before creating anything.
2. Search existing Specifications, neighboring tests, architecture docs, app
   metadata, REST/CLI/SDK/GUI surfaces, and relevant code to identify the feature.
3. If approved assertions apply, add per-test `specification-test` metadata with
   proof strength and surface, then regenerate the assertion index.
4. If no approved Specification defines the intended behavior, extract stable
   truth from the whole feature or Plan cluster, not only one test. Separate
   historical implementation choices from durable behavior.
5. Invoke `define-specification`, present the complete compact Specification, and
   wait for approval before mapping the test or changing implementation behavior.
6. Update the existing Plan with Specification references and evidence locations;
   do not replace its discovery, tasks, attempts, handoff, or evidence ledger.
7. Run `python3 scripts/specifications.py generate` and
   `python3 scripts/specifications.py check-generated` before deploy.

## Rules

- Never infer that an existing passing test is approved product truth.
- Search before creating; avoid one permanent Specification per historical Plan.
- Touched legacy tests may not remain `legacy_unmapped` at deploy.
