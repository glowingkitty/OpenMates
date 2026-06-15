---
status: active
last_verified: 2026-06-15
key_files:
- scripts/audit_frontend_dependency_pins.py
- scripts/tests/test_audit_frontend_dependency_pins.py
- package.json
- pnpm-lock.yaml
---

# Frontend Dependency Pin Audit

`scripts/audit_frontend_dependency_pins.py` is a narrow deterministic guard for frontend dependency drift that can break the web app before source code changes are involved.

The audit currently enforces:
- `@sveltejs/kit` stays pinned to the version known not to emit malformed relative static asset paths.
- `prosemirror-model` and `prosemirror-view` stay on a single lockfile version so TipTap does not load incompatible ProseMirror copies.
- all `@tiptap/*` packages in the lockfile stay on the same pinned release train.

Run it after dependency updates with:

```bash
python3 scripts/audit_frontend_dependency_pins.py
```

The focused regression tests live in `scripts/tests/test_audit_frontend_dependency_pins.py` and cover both the accepted pin set and the duplicate/drift cases that previously broke chat input and font loading.
