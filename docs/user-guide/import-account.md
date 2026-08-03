---
status: active
doc_type: how-to
audience:
  - everyday-users
  - technical-users
last_verified: 2026-08-03
tested_by:
  - spec: frontend/apps/web_app/tests/import-chats.spec.ts
    test: imports chats from ZIP in account settings and shows success results
    checkpoints:
      - import-page
      - parsed-chat-list
      - import-success
claims:
  - id: import-file-shows-parsed-chat-list
    type: e2e
    file: frontend/apps/web_app/tests/import-chats.spec.ts
    assertion: import-file-shows-parsed-chat-list
  - id: import-selected-chats-shows-success-results
    type: e2e
    file: frontend/apps/web_app/tests/import-chats.spec.ts
    assertion: import-selected-chats-shows-success-results
---

# Import Your Data

<!-- remotion-video:
slug: import-account
status: planned
purpose: Show opening Settings > Account > Import, choosing an export ZIP, reviewing parsed chats, importing selected chats, and seeing the success results.
duration_target: 45-60s
-->

> Import chats from Claude, ChatGPT, OpenCode, or an OpenMates account export.

## Summary

- Use import when you want to migrate chats from Claude, ChatGPT, OpenCode, or an OpenMates account export.
- Open **Settings > Account > Import**, choose the file, review the chats, then import the selected items.
- Imported chats appear in your chat list like regular encrypted chats.

## What It Does

Import reads supported export files in your browser, shows the chats it found, and lets you choose which chats to import. Selected plaintext messages are safety-scanned, then encrypted on your device before permanent storage.

## How to Import

1. Go to **Settings > Account > Import**.
2. Choose a supported JSON or ZIP export file.
3. Review the chats found in the file.
4. Click **Import selected chats**.
5. Wait for the success results, then open the imported chats from your chat list.

## What Is Supported

- Claude official JSON or ZIP exports.
- ChatGPT official JSON or ZIP exports.
- JSON transcripts created with `opencode export <session-id> > opencode-session.json`.
- OpenMates Account Export V1 ZIP files.
- Visible user and assistant text. OpenCode reasoning and tool payloads are not imported as chat messages.

## What Happens During Import

- OpenMates parses the file locally in your browser.
- Messages are safety-scanned before being stored in your account.
- Imported chats appear as regular encrypted chats in your chat list.
- You can delete imported chats afterwards like any other chat.

## Tips

- Import only files you trust.
- If you are testing an export, import it into a test account first.
- Delete test imports after verifying them so your chat list stays clean.

## Related

- [Export Your Data](export-account.md) -- Download your account data
- [Chats](chats.md) -- General chat management
