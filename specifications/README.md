# Specifications

Approved Specifications are the durable source of truth for product, design,
operations, research, policy, and other reusable outcomes. Implementations,
Plans, Checks, and Runs provide replaceable execution and evidence.

Each bundle contains:

```text
<category>/<name>/
|-- specification.yml
`-- examples.yml
```

Use `python3 scripts/specifications.py validate`, `generate`, `check-generated`,
`check-test`, and `check-changed` for deterministic checks. `generate` updates
the registry, assertion index, and coverage together; `apply-evidence` attaches
successful runs only when their assertion fingerprints, mapped tests, tested
commit, and hashed JSON run reports are current. Specification edits stay inside the
session worktree until `python3 scripts/sessions.py specification approval-pdf --session
<session-id> --bundle <bundle>` has uploaded an exact-fingerprint PDF containing
the complete Specification and examples.
The approval PDF shows changed-text-only diffs with inline green `+` insertions,
inline red `-` deletions, and neutral unchanged text. Its link must appear before the user
is asked to approve the exact hash. The generated JSON review artifact is then
required by `scripts/specifications.py approve --review-artifact <path>` and binds the
approval receipt to the reviewed fingerprint, baseline commit, and PDF hash.
