---
paths:
  - "scripts/code_quality_guard.py"
  - "scripts/audit_*.py"
  - ".claude/hooks/**"
---
# Code quality guardrails (summary is in CLAUDE.md)

- Smallest behavior-preserving change; no new abstractions unless they remove
  real duplication. Files >4,000 lines: find an extraction seam first; never
  rewrite a large file wholesale without approval.
- Reuse shared utilities: `BaseSkill`, `backend/shared/{python_utils,python_schemas,providers}`,
  UnifiedEmbed primitives, settings elements.
- Recurring bug/flaky/privacy/drift patterns: prefer extending an existing
  audit, guard or helper over a new script. New scripts need tests with a
  failing and a clean fixture. Hooks must be path-scoped and low-noise (check
  changed lines; expose `--all` for full scans).
- Broad catches only at boundaries, with context and re-raise or typed error.
- `python3 scripts/code_quality_guard.py` checks staged changes for generated
  files, secrets, oversized files, suppressions, broad catches and cross-skill
  or store-internal imports.
