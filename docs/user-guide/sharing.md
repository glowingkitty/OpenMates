---
status: active
doc_type: how-to
audience:
  - everyday-users
  - technical-users
last_verified: 2026-03-24
tested_by:
  - spec: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    test: creates and shares a chat link with QR code and a default short link
    checkpoints:
      - share-config-step
      - link-generated
      - qr-fullscreen
      - short-link-generated
      - with-expiration
claims:
  - id: share-panel-opens-from-chat-header
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-panel-opens-from-chat-header
  - id: share-panel-shows-link-configuration
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-panel-shows-link-configuration
  - id: share-link-has-copy-option
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-link-has-copy-option
  - id: share-link-has-qr-code
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-link-has-qr-code
  - id: share-qr-code-opens-fullscreen
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-qr-code-opens-fullscreen
  - id: share-link-uses-short-link-by-default
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-link-uses-short-link-by-default
  - id: share-link-can-have-expiration
    type: e2e
    file: frontend/apps/web_app/tests/share-chat-flow.spec.ts
    assertion: share-link-can-have-expiration
---

# Sharing

<!-- remotion-video:
slug: sharing
status: planned
purpose: Show opening the share panel from a chat, generating a default short link, copying it, opening the QR fullscreen view, and setting an expiration.
duration_target: 45-60s
-->

> Share conversations and results with others using secure, encrypted links. You control who sees what, for how long, and whether a password is required.

## Summary

- Use sharing when you want someone else to view a chat or app result without changing your original chat.
- Open the share panel from the chat header, choose your options, then copy the link or scan the QR code.
- You can add expiration, password protection, and community sharing depending on how broadly you want to share. When you are online, OpenMates creates a compact short link by default.

## What It Does

Sharing lets you send a link to a chat or embed (a result like a web page summary, code snippet, or video transcript) so others can view it. The link contains an encrypted key that only works with that specific content -- the server never sees it.

## Sharing Options

### Share Publicly

Anyone with the link can view the chat.

- The chat is **read-only**.
- If someone tries to reply, a personal copy of the chat is created in their account. The original stays unchanged.
- You can optionally enable **Share with Community**, which makes the chat eligible for discovery on the platform and social media. When community sharing is enabled, password protection and time limits are disabled automatically.

## Password Protection

You can add a password (up to 10 characters) to any shared link for extra security.

- The password encrypts the access key inside the link itself.
- OpenMates never stores or receives the password. For compact short links, OpenMates may store that a link is password-protected so social previews can hide the chat title and summary.
- If the password is wrong, the content simply cannot be decrypted.

## Link Expiration

Share links can have a time limit that you set when creating them (for example, 1 hour, 24 hours, or longer). If you do not set a limit, the share link does not expire by default.

- Expiration is checked against the server clock, so it cannot be bypassed by changing your device time.
- Once expired, the link stops working.

## Creating a Share Link

Share links are generated on your device first. When you are online, OpenMates wraps that encrypted link in a compact `/s/{token}#{key}` short link. If the short-link service is unreachable, copying and QR codes fall back to the longer encrypted `/share/...#key=...` link.

1. Open the chat or embed you want to share.
2. Set an expiration time and optional password.
3. Copy the link or scan the QR code.

## Controlling What Is Shared

- When you first share, all existing messages become visible to recipients.
- Messages you send *after* sharing are **private by default**. Recipients will not see them unless you click **Update shared chat**.
- No new link is needed after updating -- the same link shows the new content.

## Embed Sharing

Results from apps (web summaries, code, transcripts, and so on) can be shared independently of the chat they appeared in.

- Embed links work the same way as chat links: encrypted, with optional password and expiration.
- Online embed sharing uses the compact `/s/{token}#{key}` format. Offline fallback links use `/share/embed/{embed-id}#key={encrypted-key}`.

## Social Media Previews

When you share a link on social media or messaging apps, a preview (title and summary) appears automatically. This preview is generated from separate, server-readable metadata -- your actual chat content remains encrypted and private.

## Managing Shared Chats

### For the Chat Owner

- You can **unshare** a chat at any time, which revokes all access.
- You can **delete** the chat, which removes it everywhere.
- Disabling "Share with Community" removes the chat from discovery but keeps the link working.

## Tips

- Online share links are compact enough to fit in a QR code. Offline fallback links are longer but still encrypted.
- Use password protection when sharing sensitive content, even with a time limit.

## Related

- [Chats](chats.md) -- Chat management basics
- [Hidden Chats](hidden-chats.md) -- Password-protect chats on your device
- [Demo Chats](demo-chats.md) -- Community-submitted example conversations
