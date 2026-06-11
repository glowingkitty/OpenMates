---
status: active
doc_type: index
audience:
- contributors
- technical-users
last_verified: 2026-06-10
claims:
- id: arch-platforms-readme-behavior
  type: unit
  claim: Platform Architecture is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - docs/architecture/platforms/README.md
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-platforms-readme-behavior
  verified: '2026-06-11'
- id: arch-platforms-readme-index-scope
  type: manual
  reason: 'Index doc: verifies navigation scope through Markdown link validation rather than source-code anchors.'
---

# Platform Architecture

## Summary

- OpenMates currently has three implemented platform surfaces: the SvelteKit web app, the OpenMates CLI, and the Apple app.
- The web app is the primary product surface and source of truth for shared UI behavior.
- The CLI covers terminal workflows, server management, and API/WebSocket interaction.
- The Apple app is native Swift/SwiftUI and follows web parity through generated tokens and mapped source docs.

## Platform Docs

- [Web App](../frontend/web-app.md) -- SvelteKit app architecture and public docs processing.
- [CLI](cli.md) -- command-line platform architecture and capabilities.
- [Apple App](../frontend/native-apps.md) -- native app architecture and web-parity model.
