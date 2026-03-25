---
status: active
last_verified: 2026-03-24
---

# Debug Tools

> Browser-based tools for troubleshooting issues with chat sync, missing messages, or data inconsistencies.

## What It Does

OpenMates includes read-only debug commands you can run in your browser's developer console. These help you inspect your local data when something seems off, like missing messages or sync problems.

## How to Access

1. Open OpenMates in your browser.
2. Open Developer Tools (`F12` on Windows/Linux, `Cmd + Option + I` on macOS).
3. Go to the **Console** tab.
4. Type any of the commands below.

## Available Commands

All commands are **read-only** -- they inspect data but never change it.

### Inspect a Single Chat

```javascript
await window.debugChat("your-chat-id");
```

Shows:
- Chat metadata (title, timestamps, versions).
- Message count and list.
- Whether the message count matches the expected version (consistency check).

### Inspect All Chats

```javascript
await window.debugAllChats();
```

Shows:
- Total number of chats and messages on this device.
- A summary of each chat.
- Highlights any chats with data inconsistencies.

### Inspect a Single Message

```javascript
await window.debugGetMessage("message-id");
```

Shows the raw data for a specific message stored on your device.

## Troubleshooting Common Issues

### Messages Seem Missing After Refresh

1. Run `debugChat('your-chat-id')` to see how many messages are stored on your device.
2. If the count is lower than expected, the sync system should detect this and re-sync automatically on the next page load.
3. Try refreshing the page. If messages are still missing, report the issue.

### Data Does Not Match Across Devices

Compare the message count from `debugChat` on each device. If one device shows fewer messages, it may need to re-sync. Refreshing the page usually triggers this.

## Tips

- You can find a chat's ID in the browser address bar when the chat is open.
- These tools are meant for troubleshooting, not everyday use.
- If you spot a data inconsistency, please report it -- see [Issue Reporting](issue-reporting.md).

## Related

- [Issue Reporting](issue-reporting.md) -- How to report bugs
- [Chats](chats.md) -- Chat management
