---
status: active
doc_type: explanation
audience:
  - contributors
  - technical-users
last_verified: 2026-06-10
claims: []
---

# CLI Platform

## Summary

The OpenMates CLI is the terminal platform for encrypted chat operations, app skill execution, settings commands, billing helpers, and self-hosted server management.

## Canonical Architecture Docs

- [CLI Package](../apps/cli-package.md) -- package architecture, commands, crypto boundary, and server-management commands.
- [CLI Feature Parity](../apps/cli-feature-parity.md) -- web versus CLI capability matrix.
- [CLI User Guide](../../cli/README.md) -- command reference for users.

## Source Areas

- `frontend/packages/openmates-cli/src/` contains the CLI entry point, client, crypto, storage, WebSocket, and server-management code.
- `frontend/packages/openmates-cli/tests/` contains CLI contract tests.
- `docs/cli/` contains CLI user documentation.

## Related

- [Platform Architecture](README.md) -- platform index
- [Web App Platform](web-app.md) -- primary product surface
- [Apple Platform](apple.md) -- native client parity model
