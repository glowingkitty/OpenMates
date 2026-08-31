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
session worktree until `python3 scripts/contract_approval_pdf.py <bundle>` has
uploaded an exact-fingerprint PDF containing the complete Contract and examples.
The approval PDF highlights additions and modifications in yellow and preserves
removals in yellow removal blocks. Its link must appear in chat before the user
is asked to approve the exact hash. The generated JSON review artifact is then
required by `scripts/contracts.py approve --review-artifact <path>` and binds the
approval receipt to the reviewed fingerprint, baseline commit, and PDF hash.
