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

- The chat is **read-only** by default.
- If someone tries to reply, a personal copy of the chat is created in their account. The original stays unchanged.
- You can optionally enable **Share with Community**, which makes the chat eligible for discovery on the platform and social media.

### Share with a Specific Person

Invite someone by email to view or collaborate on a chat.

- The recipient receives an email with a secure link.
- Access is tied to their account, so it persists even if their email changes.
- You can choose between **read-only** and **group chat** modes.

### Group Chat Mode

When you share with specific people using group chat mode:

- All participants can send messages that everyone sees in real time.
- Type **@OpenMates** in a message to ask a digital team mate to respond. Without the mention, messages are just between the people in the chat.
- Each participant needs a **public username** (created on first use, unique across the platform). You can also set an optional display name.

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
2. Choose your sharing option (public, specific person, or group chat).
3. Set an expiration time and optional password.
4. Copy the link or scan the QR code.

## Controlling What Is Shared

### Read-Only Chats

- When you first share, all existing messages become visible to recipients.
- Messages you send *after* sharing are **private by default**. Recipients will not see them unless you click **Update shared chat**.
- No new link is needed after updating -- the same link shows the new content.

### Group Chats

- All messages (from any participant) are visible to everyone in real time.
- No manual update step is needed.

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

### For Recipients

- **Read-only chats**: You can download or copy the content. Use "Leave" to remove it from your sidebar.
- **Group chats**: You can leave the group. Your past messages remain visible to others.

## Tips

- Share links are compact enough to fit in a QR code.
- Use password protection when sharing sensitive content, even with a time limit.
- Group chat mode works well for team discussions where you want a digital team mate available on demand.

## Related

- [Chats](chats.md) -- Chat management basics
- [Hidden Chats](hidden-chats.md) -- Password-protect chats on your device
- [Demo Chats](demo-chats.md) -- Community-submitted example conversations
