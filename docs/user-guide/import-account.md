---
status: active
doc_type: how-to
audience:
  - everyday-users
  - technical-users
last_verified: 2026-06-03
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

> Restore chats from an OpenMates export ZIP or chat YAML file.

## Summary

- Use import when you want to restore chats from an OpenMates export ZIP or chat YAML file.
- Open **Settings > Account > Import**, choose the file, review the chats, then import the selected items.
- Imported chats appear in your chat list like regular encrypted chats.

## What It Does

Import lets you bring previously exported OpenMates chats back into your account. The import screen reads the file in your browser, shows the chats it found, and lets you choose which chats to import. Supported embedded data, including exported code snippets and images, is restored with the chat.

## How to Import

1. Go to **Settings > Account > Import**.
2. Choose an OpenMates export ZIP or chat YAML file.
3. Review the chats found in the file.
4. Click **Import selected chats**.
5. Wait for the success results, then open the imported chats from your chat list.

## What Is Supported

- Account export ZIP files from OpenMates.
- Individual chat YAML files from OpenMates.
- Multiple chats in one ZIP file.
- Decrypted chat text and supported embedded data included in the export.
- Exported code snippets and image embeds from OpenMates chat exports.

## What Happens During Import

- OpenMates parses the file locally in your browser.
- Messages are safety-scanned before being stored in your account.
- Imported chats appear as regular encrypted chats in your chat list.
- Supported embedded data is restored inside those chats when it is included in the import file.
- You can delete imported chats afterwards like any other chat.

## Tips

- Import only files you trust.
- If you are testing an export, import it into a test account first.
- Delete test imports after verifying them so your chat list stays clean.

## Related

- [Export Your Data](export-account.md) -- Download your account data
- [Chats](chats.md) -- General chat management
