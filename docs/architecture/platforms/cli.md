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

## Chat sidebar and nested Projects

The TUI shows globally running parent chats above a flat Project navigator. Deep
locations use the actual root Project name, a middle ancestor picker and the
current folder name; increasing depth does not indent or narrow chat rows.
Running descendants activate both their parent chat and containing folders.
`/active` reveals the running rows. The command palette also exposes
`/chat-add-to-project`, `/chat-move-to-project`, `/chat-create-project` and
`/chat-subfolder` for the selected chat or Project location.

Chat grouping requests an AI title from bounded chat titles only. Project names
and chat associations use the existing client-side encryption. Moving a chat
writes its destination association before removing other Project associations.
Chat-only creation leaves the file write policy awaiting explicit selection.

The SDK methods `getChatActivity`, `getSidebarChats` and `planProjectAsk`
support these flows. `tuiChatSidebar.test.ts` checks activity grouping, hidden
branch suppression, recursive folders and terminal widths; `sdk-chat-sidebar.test.ts`
checks the metadata and title-only request boundaries.

## Related

- [Platform Architecture](README.md) -- platform index
- [Web App Platform](web-app.md) -- primary product surface
- [Apple Platform](apple.md) -- native client parity model
