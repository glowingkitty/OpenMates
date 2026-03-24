---
status: active
last_verified: 2026-03-24
---

# Hidden Chats

> Protect sensitive conversations with a password. Hidden chats are invisible in your main chat list until you unlock them.

## What It Does

Hidden chats let you add an extra layer of protection to specific conversations. When you hide a chat, it disappears from your normal chat list and can only be viewed after entering the correct password. The server cannot tell which chats are hidden -- this is handled entirely on your device.

## How to Use It

### Hiding a Chat

1. Right-click (or long-press) on a chat in the sidebar.
2. Select **Hide** from the context menu.
3. Enter a password (4-30 characters). You can reuse a password you have used before or create a new one.

### Viewing Hidden Chats

1. Click **Show hidden chats** at the top of the chat list. This link is always visible, whether or not you have hidden chats -- so no one can tell just by looking.
2. Enter your password.
3. Any chats protected with that password will appear in a separate section above your main chat list.

### Locking Hidden Chats

- Click **Lock hidden chats** to immediately hide them again.
- Hidden chats also **lock automatically** after a period of inactivity.
- When locked, the content is cleared from memory -- it is not just visually hidden, it is actually removed from the screen and device memory.

### Multiple Passwords

You can use different passwords for different chats. When you unlock, only the chats matching the password you entered will appear. This lets you create separate groups of hidden conversations.

## Multi-Device Support

Hidden chats sync across your devices like any other chat. To view them on another device, just enter the same password. The password itself is never sent to the server.

## Security Details

- **Zero-knowledge**: The server never sees your password or knows which chats are hidden.
- **No visible flag**: There is no database marker that identifies a chat as hidden. The system simply tries to decrypt it -- if the normal method fails, it knows the chat is password-protected.
- **Brute-force protection**: After 3 incorrect password attempts, you are locked out for 30 seconds.

## Tips

- Choose a memorable but strong password. Since the password is combined with your account key, even a shorter password provides good security.
- If you forget the password, the hidden chat content cannot be recovered -- by design.
- "Show hidden chats" always appears in the sidebar, even when you have no hidden chats. This prevents someone from guessing that you have hidden conversations.

## Related

- [Chats](chats.md) -- General chat management
- [Incognito Mode](incognito-mode.md) -- Chats that disappear when you close the tab
