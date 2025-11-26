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

3. **Sharing Modes:**
   - **Read-Only Mode:** Recipients can view the chat and its messages but cannot send new messages. This mode is ideal for sharing completed conversations or knowledge base material.
   - **Collaborative Group Chat Mode:** Recipients can read and contribute to the chat by sending messages. This enables team collaboration on shared conversations. In this mode, users need to explicitly mention **@OpenMates** to trigger OpenMates to respond in the conversation. This design allows groups to discuss and collaborate naturally without OpenMates responding to every message, making it suitable for team discussions and collaborative problem-solving.

4. **Security:**
   - The encryption key is included in the link initially, but is automatically stored securely after first access
   - The key is removed from the URL after being saved to prevent exposure
   - On subsequent visits, the stored key is used automatically
   - **Password Protection (Optional):** Users can optionally set a password when sharing a chat. The password is used to derive an additional encryption key that is combined with the shared encryption key, providing an extra layer of security. The server has no knowledge of whether a chat is password-protected (true zero-knowledge).

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

## Password Protection

Users can optionally set a password when sharing a chat or embed to add an additional layer of security. The password protection works as follows:

### Password-Based Encryption

1. **Password Derivation:**
   - When a user sets a password for sharing, a random salt is generated client-side
   - The password is combined with the salt and processed through PBKDF2 (100,000 iterations, SHA-256) to derive a 256-bit encryption key
   - The password-derived key is combined with the shared encryption key using a key derivation function (KDF)
   - The combined key is used to encrypt the shared content
   - **No server storage:** The server never stores any password-related information (no hash, no salt, no indication of password protection)

2. **Encryption Process:**
   - If password is set: Content is encrypted with `shared_encryption_key + password-derived key`
   - If no password: Content is encrypted with `shared_encryption_key` only
   - This ensures that even if someone obtains the shared encryption key from the URL, they cannot decrypt password-protected content without the password

3. **Access Flow (Zero-Knowledge):**
   - When someone accesses a shared chat:
     1. Client extracts `chat_id` and `key` from URL fragment
     2. Client sends request to server with `chat_id` (key stays in fragment)
     3. Server checks if chat exists and is shared, then returns encrypted content
     4. Client attempts to decrypt content using `shared_encryption_key` from URL fragment
     5. **If decryption succeeds:** Content is displayed ✅
     6. **If decryption fails:**
        - Client prompts user: "Enter the password:"
        - User enters password (if applicable)
        - Client derives key from password using the same salt generation method (salt must be deterministically derived or stored client-side)
        - Client combines password-derived key with `shared_encryption_key`
        - Client attempts decryption again with combined key
        - If decryption succeeds: Content is displayed ✅
        - If decryption still fails: Show error: "Unable to decrypt. Please verify the link and password (if required)."

4. **Security Properties:**
   - **True Zero-Knowledge:** Server has no knowledge of password protection - it cannot distinguish between password-protected and non-password-protected shares
   - **No Server Storage:** No password hash, salt, or any password-related data is stored on the server
   - **Brute Force Protection:** Failed decryption attempts provide no feedback, making brute force attacks impractical
   - **Key Combination:** Password-derived key is combined with shared key, so both are required for decryption
   - **Salt Management:** Salt must be deterministically derived (e.g., from chat_id/embed_id) or stored client-side (e.g., in URL fragment or local storage) to allow password derivation on access

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

## Embed Sharing

Embeds (app skill results, files, code, etc.) can be shared independently of chats using the same zero-knowledge architecture. See [Embeds Architecture](./embeds.md) for detailed information.

### Key Similarities

- **URL Pattern**: Shared embed links use the format `/#embed-id={embed_id}&key={shared_encryption_key}` where both the embed ID and encryption key are stored in the URL fragment
- **Server Privacy**: The URL fragment is never sent to the server - it remains entirely on the client side
- **Zero-Knowledge Encryption**: All embed content remains encrypted, even when shared
- **Access Control**: Server checks `share_mode` ('private', 'shared_with_user', 'public') and `shared_with_users` array for access control

### Access Flow

When someone opens a shared embed link:

1. Client extracts `embed_id` and `key` from URL fragment
2. Client sends request to server with `embed_id` (key stays in fragment, never sent to server)
3. Server checks:
   - Does embed exist?
   - If `share_mode === 'public'`: Return encrypted content
   - If `share_mode === 'shared_with_user'`: Check if user's `hashed_user_id` is in `shared_with_users` array
     - If yes: Return encrypted content
     - If no: Return error
   - If `share_mode === 'private'`: Return error
4. If access granted: Server returns encrypted content (server has no knowledge of password protection)
5. Client attempts to decrypt content using `shared_encryption_key` from URL fragment
6. **If decryption succeeds:** Content is displayed ✅
7. **If decryption fails:**
   - Client prompts user: "Unable to decrypt. If this share is password-protected, enter the password:"
   - User enters password (if applicable)
   - Client derives key from password (using deterministic salt or client-stored salt)
   - Client combines password-derived key with `shared_encryption_key` from URL fragment
   - Client attempts decryption again with combined key
   - If decryption succeeds: Content is displayed ✅
   - If decryption still fails: Show error: "Unable to decrypt. Please verify the link and password (if required)."
8. If access denied or embed doesn't exist: Show unified error message: "Embed can't be found. Either it doesn't exist or you don't have access to it."

### Differences from Chat Sharing

- **Independent of Chats**: Embeds can be shared without sharing the entire chat
- **No Message Visibility Control**: Embeds are shared as complete entities (no timestamp-based cutoff)
- **Cross-Chat References**: Shared embeds can be referenced in multiple chats
