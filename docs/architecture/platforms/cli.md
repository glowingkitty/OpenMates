---
status: active
doc_type: explanation
audience:
- contributors
- technical-users
last_verified: 2026-06-10
key_files:
- frontend/packages/openmates-cli/src/cli.ts
- frontend/packages/openmates-cli/src/client.ts
- frontend/packages/openmates-cli/src/ws.ts
claims:
- id: arch-platforms-cli-behavior
  type: unit
  claim: CLI Platform is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/packages/openmates-cli/src/cli.ts
  - frontend/packages/openmates-cli/src/client.ts
  - frontend/packages/openmates-cli/src/ws.ts
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-platforms-cli-behavior
  verified: '2026-06-11'
- id: arch-platforms-cli-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-cli-source-1
  anchors:
  - type: file_exists
    path: frontend/packages/openmates-cli/src/cli.ts
- id: arch-platforms-cli-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-cli-source-2
  anchors:
  - type: file_exists
    path: frontend/packages/openmates-cli/src/client.ts
- id: arch-platforms-cli-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-cli-source-3
  anchors:
  - type: file_exists
    path: frontend/packages/openmates-cli/src/ws.ts
---

# CLI Platform

## Summary

The OpenMates CLI is the terminal platform for encrypted chat operations, app skill execution, settings commands, billing helpers, and self-hosted server management.

## Canonical Architecture Docs

- [CLI Package](cli-package.md) -- package architecture, commands, crypto boundary, and server-management commands.
- [CLI Feature Parity](cli-feature-parity.md) -- web versus CLI capability matrix.
- [CLI User Guide](../../user-guide/cli/README.md) -- command reference for users.

## Source Areas

- `frontend/packages/openmates-cli/src/` contains the CLI entry point, client, crypto, storage, WebSocket, and server-management code.
- `frontend/packages/openmates-cli/tests/` contains CLI contract tests.
- `docs/user-guide/cli/` contains CLI user documentation.

## Related

- [Platform Architecture](README.md) -- platform index
- [Web App Platform](web-app.md) -- primary product surface
- [Apple Platform](apple.md) -- native client parity model
