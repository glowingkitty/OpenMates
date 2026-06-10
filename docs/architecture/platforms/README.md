---
status: active
doc_type: index
audience:
  - contributors
  - technical-users
last_verified: 2026-06-10
claims: []
---

# Platform Architecture

## Summary

- OpenMates currently has three implemented platform surfaces: the SvelteKit web app, the OpenMates CLI, and the Apple app.
- The web app is the primary product surface and source of truth for shared UI behavior.
- The CLI covers terminal workflows, server management, and API/WebSocket interaction.
- The Apple app is native Swift/SwiftUI and follows web parity through generated tokens and mapped source docs.

## Platform Docs

- [Web App](../frontend/web-app.md) -- SvelteKit app architecture and public docs processing.
- [CLI](../../cli/README.md) -- command-line usage and platform capabilities.
- [Apple App](../frontend/native-apps.md) -- native app architecture and web-parity model.
