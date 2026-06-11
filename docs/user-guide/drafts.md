---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-11
claims:
  - id: user-guide-drafts-source
    type: unit
    claim: Draft behavior is grounded in current draft persistence sources.
    file: scripts/tests/test_user_guide_product_docs_claims.py
    assertion: user-guide-drafts-source
---

# Drafts

> Unsent messages are automatically saved and synced across your devices so you never lose what you were typing.

## What It Does

When you start typing a message but do not send it, OpenMates saves it as a draft. Drafts are encrypted on your device before being synced, just like your messages. If you switch devices, your draft will be waiting for you in the same chat.

## How It Works

1. **You start typing** in any chat.
2. After a brief pause (about 1 second), the draft is saved locally and synced to the server.
3. On another device, the draft appears automatically in the message input field for that chat.
4. Sending the message clears the draft. Deleting all the text also clears it.

## Draft Indicators

- Chats with unsent drafts show a draft indicator in the chat list.
- The chat list updates when drafts are added or removed.

## Offline Support

If you are offline, draft changes are saved locally and synced when your connection returns.

## Tips

- Drafts sync in real time. If you type on your phone and then open your laptop, the draft appears almost instantly.
- There is no manual "save draft" button -- it happens automatically.
- Drafts are encrypted with the same level of protection as your messages.

## Related

- [Chats](chats.md) -- Chat management
- [Keyboard Shortcuts](keyboard-shortcuts.md) -- Quick navigation
