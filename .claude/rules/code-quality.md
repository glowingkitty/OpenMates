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
- Package installs (owner, 21 Nov): a version is installable only after 7 days
  public (npm: `minimumReleaseAge` in `pnpm-workspace.yaml`; CI:
  `supply-chain-guard.yml`), unless it fixes a CISA-KEV exploited flaw; pip uses
  hashes. The Bash hook (`scripts/install_age_hook.py`) refuses ad-hoc
  `npm/pnpm/yarn add`, `pip install`, `uv add`, `cargo add/install`. Run
  `python3 scripts/install_age_guard.py check --ecosystem <npm|PyPI|crates.io>
  --name <pkg> [--version V] [--kev CVE]`, then re-run with the prefix
  `OPENMATES_AGE_CHECKED=<eco>:<pkg>@<V>` and the exact `<pkg>@<V>` spec (the
  hook re-checks). Lockfile/frozen installs and `pip -r X --require-hashes` stay allowed.
