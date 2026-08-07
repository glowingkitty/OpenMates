# Contracts

Approved contracts are the durable source of truth for product behavior, data
models, architecture boundaries, and platform parity. Implementations, tests,
and specs provide replaceable code and evidence against that truth.

Each bundle contains:

```text
<category>/<name>/
|-- contract.yml
`-- examples.yml
```

Use `python3 scripts/contracts.py validate`, `generate`, `check-generated`,
`check-test`, and `check-changed` for deterministic checks. `generate` updates
the registry, assertion index, and coverage together; `apply-evidence` attaches
successful runs only when their assertion fingerprints, mapped tests, tested
commit, and hashed JSON run reports are current. Contract edits stay inside the
session worktree until the full new contract or explicit changes are shown in
chat and an exact-hash approval is recorded.
