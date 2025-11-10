# Share chat architecture

> **Note:** This feature is not yet implemented. This document describes the planned architecture.
>
> **For technical details:** See the [database schema](../../backend/core/directus/schemas/chats.yml) for field names and data structure.

## Overview

The share chat feature allows users to share their conversations with other users or make them publicly accessible. All shared chats remain encrypted, ensuring privacy even when shared.

## Sharing Options

### Share with User

When sharing with a specific user:

1. **Sharing Process:**
   - The chat owner enters the recipient's email address
   - An email notification is sent to the recipient with a secure link to access the chat
   - The link uses the format: `/#chat-id={chatid}&key={encryption-key}` where both the chat ID and encryption key are stored in the URL fragment (after the `#`)
   - The system verifies that the recipient is authorized to view the chat

2. **Access Management:**
   - The recipient's access is tied to their account, so they can continue accessing the chat even if their email address changes
   - Access persists as long as the chat remains shared with them

3. **Security:**
   - The encryption key is included in the link initially, but is automatically stored securely after first access
   - The key is removed from the URL after being saved to prevent exposure
   - On subsequent visits, the stored key is used automatically

### Share with Public

When sharing publicly:

- Similar security and encryption principles apply
- Anyone with the link can access the chat (no email verification required)
- The system checks if the chat is marked as publicly shared before allowing access

## Privacy and Security

- **URL Pattern:** Shared chat links use the format `/#chat-id={chatid}&key={encryption-key}` where both the chat ID and encryption key are stored in the URL fragment (everything after the `#` symbol)
- **Server Privacy:** The URL fragment is never sent to the server - it remains entirely on the client side. This means the server never receives or sees the chat ID or encryption key, ensuring maximum privacy
- **Search Engine Protection:** Shared chats are designed to prevent search engine indexing since the fragment portion of URLs is not accessible to search engines
- **Zero-Knowledge Encryption:** All messages remain encrypted, even when shared

## Message Visibility Control

### Initial Sharing

When a chat is first shared:

- **All existing messages are shared:** When sharing is enabled, all messages up to the most recent one at that moment are immediately available to shared users
- The system records the timestamp of the most recent message at the time of sharing
- This timestamp defines the cutoff point for what shared users can access

### Follow-up Messages

After sharing a chat:

- **New messages are private by default:** When the chat owner sends follow-up messages after sharing, these new messages are not automatically included in the shared version
- Shared users cannot see these newer messages until the owner explicitly updates the shared chat
- This gives the owner control over when to make new content visible to others

### Updating Shared Content

To include newer messages in the shared chat:

- The chat owner clicks the "Update shared chat" button in the interface
- This action updates the timestamp cutoff point to include all messages up to the most recent one
- No new share link is needed - the existing link continues to work, but now shows the updated content
- The UI clearly indicates which messages are currently shared and which remain private

## User Interface Requirements

The interface must provide clear visual feedback:

- **Visual Boundary:** A clear divider or indicator showing where the shared portion ends
- **Message Status:** Users can easily see which messages are shared and which are private
- **Update Control:** An "Update shared chat" button allows owners to easily extend the shared portion to include more recent messages
- **Sync Status:** The interface shows which messages are synced with the shared version and allows owners to update the shared content

This design enables flexible, secure sharing while maintaining user control over privacy and message visibility.
