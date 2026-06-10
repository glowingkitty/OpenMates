---
status: active
doc_type: explanation
audience:
  - contributors
  - technical-users
last_verified: 2026-06-10
claims: []
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
