---
status: active
doc_type: explanation
audience:
  - contributors
last_verified: 2026-08-07
claims:
  - id: semantic-layer-contract-workflow
    type: static
    file: scripts/tests/test_contract_docs.py
    assertion: semantic-layer-contract-workflow
---

# Semantic Architecture Layer

Semantic pages explain how a domain works, why its boundaries exist, which
approved contracts govern it, and what changes affect neighboring areas. They do
not duplicate field constraints, examples, test filenames, or implementation
evidence from contracts and specs.

```text
Approved contract   -> durable required truth
Semantic page       -> architecture meaning and rationale
Full spec           -> changing implementation and evidence ledger
User documentation  -> how people use the behavior
```

Pages use concise Markdown with structured frontmatter. Optional diagrams use
ASCII so they remain readable in terminal and OpenCode chats. Recent history is
derived from contract-aware commits and archived specs rather than copied into
every page.
