---
status: active
doc_type: explanation
audience:
- contributors
- technical-users
last_verified: 2026-06-10
key_files:
- frontend/apps/web_app/src/routes/+layout.svelte
- frontend/apps/web_app/scripts/process-docs.js
- frontend/packages/ui/src/components/ChatHistory.svelte
claims:
- id: arch-platforms-web-app-behavior
  type: unit
  claim: Web App Platform is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/apps/web_app/src/routes/+layout.svelte
  - frontend/apps/web_app/scripts/process-docs.js
  - frontend/packages/ui/src/components/ChatHistory.svelte
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-platforms-web-app-behavior
  verified: '2026-06-11'
- id: arch-platforms-web-app-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-web-app-source-1
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/routes/+layout.svelte
- id: arch-platforms-web-app-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-web-app-source-2
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/scripts/process-docs.js
- id: arch-platforms-web-app-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-web-app-source-3
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/components/ChatHistory.svelte
---

# Web App Platform

## Summary

The SvelteKit web app is the primary OpenMates product surface. It hosts the unauthenticated product experience, authenticated chat app, settings, public legal chats, and generated documentation pages.

## Canonical Architecture Docs

- [Web App Architecture](../frontend/web-app.md) -- app shell, demo chats, legal chat infrastructure, and app routing.
- [Docs Web App](../frontend/docs-web-app.md) -- generated `/docs` pages, manifest processing, and public docs exclusions.
- [Design Tokens](../frontend/design-tokens.md) -- shared token pipeline used by web and Apple clients.

## Source Areas

- `frontend/apps/web_app/` contains the SvelteKit app and docs generation scripts.
- `frontend/packages/ui/` contains shared UI components, styles, tokens, stores, and i18n sources.
- `frontend/apps/web_app/tests/` contains Playwright coverage for web product flows.

## Related

- [Platform Architecture](README.md) -- platform index
- [Apple Platform](apple.md) -- native client parity model
- [CLI Platform](cli.md) -- terminal client and SDK
