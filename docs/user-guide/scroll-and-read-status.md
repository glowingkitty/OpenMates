---
status: active
last_verified: 2026-03-24
---

# Scroll Position & Read Status

> OpenMates remembers where you left off in each chat and syncs that position across your devices.

## What It Does

When you switch between chats or devices, OpenMates returns you to the exact spot where you stopped reading. It also tracks which chats have unread responses so you can see at a glance where new content is waiting.

## How Read Status Works

A chat is marked as **read** when you scroll to the bottom and see the latest message. Until then, an unread badge appears on the chat in your sidebar.

- **Automatic**: Scrolling to the bottom marks the chat as read on all your devices.
- **Manual**: Right-click a chat and select "Mark as Read" to clear the badge without opening it.

## How Scroll Position Syncs

Your scroll position is saved based on the **last message you had on screen** -- not a pixel position. This means it works correctly regardless of screen size or device.

1. As you scroll, the app notes which message is visible (with a brief delay to avoid excessive updates).
2. That position is saved locally and synced to the server.
3. When you open the same chat on another device, it scrolls to that message with a small offset so you can see the previous message for context.

### Edge Cases

| Situation | What happens |
|-----------|-------------|
| Message was deleted | Falls back to the bottom of the chat |
| No saved position | Opens at the bottom (newest messages) |
| Scrolling on two devices at once | The most recent position wins |
| New messages arrive while reading | The chat does not auto-scroll if you have scrolled up |

## Tips

- If you want to quickly jump to the latest messages, use `Ctrl/Cmd + Shift + Down`.
- Unread badges update in real time across all your devices.
- The scroll offset is set to show about one message of context above your last position, so you never lose your place.

## Related

- [Chats](chats.md) -- Chat management
- [Notifications](notifications.md) -- Getting alerted about new responses
- [Keyboard Shortcuts](keyboard-shortcuts.md) -- Scroll shortcuts
