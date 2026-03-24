---
status: active
last_verified: 2026-03-24
---

# Sharing

> Share conversations and results with others using secure, encrypted links. You control who sees what, for how long, and whether a password is required.

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
- The server has no knowledge of whether a password is set -- true zero-knowledge protection.
- If the password is wrong, the content simply cannot be decrypted.

## Link Expiration

Every share link has a time limit that you set when creating it (for example, 1 hour, 24 hours, or longer).

- Expiration is checked against the server clock, so it cannot be bypassed by changing your device time.
- Once expired, the link stops working.

## Creating a Share Link

Share links are generated entirely on your device -- no internet connection is needed to create one.

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
- The link format is `/share/embed/{embed-id}#key={encrypted-key}`.

## Social Media Previews

When you share a link on social media or messaging apps, a preview (title and summary) appears automatically. This preview is generated from separate, server-readable metadata -- your actual chat content remains encrypted and private.

## Managing Shared Chats

### For the Chat Owner

- You can **unshare** a chat at any time, which revokes all access.
- You can **delete** the chat, which removes it everywhere.
- Disabling "Share with Community" removes the chat from discovery but keeps the link working.

## Tips

- Share links are compact enough to fit in a QR code.
- Use password protection when sharing sensitive content, even with a time limit.

## Related

- [Chats](chats.md) -- Chat management basics
- [Hidden Chats](hidden-chats.md) -- Password-protect chats on your device
- [Demo Chats](demo-chats.md) -- Community-submitted example conversations
