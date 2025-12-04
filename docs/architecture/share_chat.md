# Share chat architecture

> **Note:** This feature is not yet implemented. This document describes the planned architecture.
>
> **For technical details:** See the [database schema](../../backend/core/directus/schemas/chats.yml) for field names and data structure.

## Overview

The share chat feature allows users to share their conversations with other users or make them publicly accessible. All shared chats remain encrypted, ensuring privacy even when shared.

## Offline-First Sharing Architecture

The sharing feature is designed to work **completely offline** when generating share links. No server request is required to create a shareable link with encryption key and optional time limits.

### Key Blob Structure

When generating a share link, the system creates an encrypted **key blob** that contains:

**Blob Contents (conceptual structure):**

- `chat_encryption_key`: The encryption key for the chat (256-bit key, may be password-encrypted)
- `generated_at`: Unix timestamp when the share link was created
- `duration_seconds`: Expiration duration in seconds (e.g., 3600 for 1 hour, 86400 for 24 hours)
- `pwd`: Password protection flag (0 = no password, 1 = password required)

**Key Points:**

- The blob always contains: `chat_encryption_key`, `generated_at`, `duration_seconds`, and `pwd` flag
- The `pwd` flag indicates whether password protection is enabled (1) or not (0)
- If `pwd=1`, the `chat_encryption_key` value inside the blob is itself encrypted with a password-derived key
- The entire blob is always encrypted with a key derived from the chat ID: `KDF(chat_id) → derived_key`
- This ensures consistent encryption approach regardless of password protection

**Blob Format:**

- The blob is stored as **URL-encoded parameters** before encryption: `chat_encryption_key=...&generated_at=...&duration_seconds=...&pwd=0`
- This format is more compact than JSON and easier to parse after decryption
- After encryption with AES-GCM and base64 URL-safe encoding, the blob becomes a single string in the URL fragment

**URL Length Characteristics:**

- **Without password:** Encrypted blob size ~150-200 base64 characters
- **With password (max 10 chars):** Encrypted blob size ~230-250 base64 characters
- **Total URL length:** ~300-320 characters (including domain, path, and fragment)
- **QR Code compatibility:** Well within QR code limits (max 2,953 chars for version 40)
- URL fragments (after `#`) are not sent to servers, so they can be longer than query parameters
- The encrypted blob is base64 URL-safe encoded (uses `-` and `_` instead of `+` and `/`)
- **Without password:** Encrypted blob size ~150-200 base64 characters
- **With password (max 10 chars):** Encrypted blob size ~230-250 base64 characters
- **Total URL length:** ~300-320 characters (including domain, path, and fragment)
- **QR Code compatibility:** Well within QR code limits (max 2,953 chars for version 40)
- URL fragments (after `#`) are not sent to servers, so they can be longer than query parameters
- The encrypted blob is base64 URL-safe encoded (uses `-` and `_` instead of `+` and `/`)

### Without Password Protection

1. **Sharer (offline):**
   - Generate random encryption key for the chat
   - Record current time: `generated_at`
   - Set duration: `duration_seconds` (e.g., 3600 for 1 hour, 86400 for 24 hours, etc.)
   - Create key blob with: `chat_encryption_key` (plaintext), `generated_at`, `duration_seconds`, `pwd=0`
   - Encrypt blob with a **fixed key derived from chat ID**: `KDF(chat_id) → derived_key`
   - Generate URL: `/share/chat/{chat-id}#key={encrypted_blob}`
   - Share link + QR code (entirely offline, no server needed)

2. **Receiver:**
   - Loads URL, extracts `key` parameter from fragment
   - Derives decryption key from chat ID: `KDF(chat_id) → derived_key`
   - Decrypts blob → extracts `chat_encryption_key`, `generated_at`, `duration_seconds`, `pwd`
   - Checks `pwd` flag: if `pwd=0`, proceed directly
   - Fetches chat from server (server provides current time)
   - Validates: `server_time - generated_at ≤ duration_seconds`
   - If valid: uses `chat_encryption_key` to decrypt chat data locally
   - If expired: show error "This chat link has expired"

### With Password Protection

1. **Sharer (offline):**
   - Generate random encryption key for the chat
   - User enters password
   - Record current time: `generated_at`
   - Set duration: `duration_seconds`
   - Encrypt `chat_encryption_key` with password-derived key: `KDF(password) → password_derived_key`, then `AES_encrypt(chat_encryption_key, password_derived_key) → encrypted_chat_key`
   - Create key blob with: `chat_encryption_key=encrypted_chat_key`, `generated_at`, `duration_seconds`, `pwd=1`
   - Encrypt entire blob with chat-ID-derived key: `KDF(chat_id) → derived_key`, then `AES_encrypt(key_blob, derived_key)`
   - Generate URL: `/share/chat/{chat-id}#key={encrypted_blob}`
   - Share link + QR code (entirely offline, no server needed)

2. **Receiver:**
   - Loads URL, extracts `key` parameter from fragment
   - Derives decryption key from chat ID: `KDF(chat_id) → derived_key`
   - Decrypts blob with chat-ID-derived key → extracts `chat_encryption_key` (still encrypted), `generated_at`, `duration_seconds`, `pwd`
   - Checks `pwd` flag: if `pwd=1`, password is required
   - Prompts user: "This chat requires a password"
   - User enters password
   - Derives decryption key from password: `KDF(password) → password_derived_key`
   - Decrypts `chat_encryption_key` with password-derived key → extracts actual `chat_encryption_key`
   - Fetches chat from server (server provides current time)
   - Validates: `server_time - generated_at ≤ duration_seconds`
   - If valid: uses `chat_encryption_key` to decrypt chat data locally
   - If expired: show error "This chat link has expired"
   - If password incorrect: decryption of `chat_encryption_key` fails, prompt again or show error

### Expiration Validation - Tamper-Proof Design

**Why this approach is tamper-proof:**

- The `generated_at` and `duration_seconds` are encrypted inside the blob and immutable
- Users cannot modify them without the encryption key
- Expiration validation uses **server time** (not client time), which prevents clock-manipulation attacks
- Even if a user sets their device clock to the future, the server time check will catch it
- There's no client-side expiration check that could be bypassed—the server provides authoritative time

**User Clock Manipulation Scenario:**
- Attacker generates a 1-hour link at 12:00 PM
- Attacker sets their device clock forward to 2:00 PM and tries to access the link
- Client receives server time: 12:10 PM (the real server time)
- Validation check: `12:10 - 12:00 ≤ 3600` ✓ Still valid
- Server time is authoritative, attacker's clock doesn't matter

## Sharing Options

### Share with Public

When sharing publicly:

1. **Sharing Process:**
   - The chat owner clicks "Share public" to make the chat publicly accessible
   - A shareable link is generated with the format: `/share/chat/{chat-id}#key={encryption-key}` where the chat ID is in the path and the encryption key blob is stored in the URL fragment (after the `#`)
   - Anyone with the link can access the chat (no email verification required)
   - The system checks if the chat is marked as publicly shared before allowing access

2. **Access Mode:**
   - **Read-Only by Default:** Public shared chats are read-only by default
   - **User Response Behavior:** If a user attempts to respond to a public read-only chat:
     - The chat is automatically copied to the user's account
     - The user's follow-up messages and assistant responses are only visible to that user
     - The original shared chat remains unchanged and unaffected
     - This ensures that public shares remain stable and don't get cluttered with individual user interactions

3. **Security:**
   - Similar security and encryption principles apply as with user-specific sharing
   - The encryption key is included in the link initially, but is automatically stored securely after first access
   - The key is removed from the URL after being saved to prevent exposure
   - On subsequent visits, the stored key is used automatically
   - **Password Protection (Optional):** Users can optionally set a password when sharing publicly. The password is used to derive an additional encryption key that is combined with the shared encryption key, providing an extra layer of security. The server has no knowledge of whether a chat is password-protected (true zero-knowledge).

### Share with User (Invite via Email)

When sharing with specific users:

1. **Sharing Process:**
   - The chat owner enters the recipient's email address
   - An email notification is sent to the recipient with a secure link to access the chat
   - The link uses the format: `/share/chat/{chat-id}#key={encryption-key}` where the chat ID is in the path and the encryption key is stored in the URL fragment (after the `#`)
   - The system verifies that the recipient is authorized to view the chat

2. **Access Management:**
   - The recipient's access is tied to their account, so they can continue accessing the chat even if their email address changes
   - Access persists as long as the chat remains shared with them

3. **Sharing Modes:**
   - **Read-Only Mode:** Recipients can view the chat and its messages. If a recipient attempts to respond:
     - The chat is automatically copied to the recipient's account
     - The recipient's follow-up messages and assistant responses are only visible to that recipient
     - The original shared chat remains unchanged and unaffected
     - This mode is ideal for sharing completed conversations or knowledge base material

   - **Group Chat Mode:** Recipients can read and contribute to the chat by sending messages. This enables true team collaboration on shared conversations:
     - **Message Synchronization:** All messages sent by any user are synced and visible to all users who have access to the chat
     - **OpenMates Mentions:** Users must explicitly mention **@OpenMates** to trigger OpenMates to respond in the conversation
     - **Natural Collaboration:** Without @OpenMates mentions, the chat acts as a regular conversation between people, allowing groups to discuss and collaborate naturally
     - **Public Usernames:** When a chat is first converted to a group chat, users are prompted to create a unique public username (globally unique across the entire OpenMates server). Users can also set an optional display name that shows instead of the public username to others in the chat
     - This design makes group chats suitable for team discussions and collaborative problem-solving

4. **Security:**
   - The encryption key is included in the link initially, but is automatically stored securely after first access
   - The key is removed from the URL after being saved to prevent exposure
   - On subsequent visits, the stored key is used automatically
   - **Password Protection (Optional):** Users can optionally set a password when sharing a chat. The password is used to derive an additional encryption key that is combined with the shared encryption key, providing an extra layer of security. The server has no knowledge of whether a chat is password-protected (true zero-knowledge).

## Public Usernames and Group Chat Identity

### Public Username Requirements

When a chat is converted to a group chat mode (for user-specific sharing), users need to establish a public identity:

1. **First-Time Setup:**
   - When a chat owner first enables group chat mode, they are prompted to create a unique public username
   - The public username must be globally unique across the entire OpenMates server
   - This username is used to identify users in group chat conversations

2. **Username Properties:**
   - **Uniqueness:** Must be unique across all OpenMates users (server-wide validation)
   - **Persistence:** Once created, the public username is tied to the user's account
   - **Visibility:** The public username is visible to all participants in group chats where the user is involved

3. **Display Name (Optional):**
   - Users can set an optional display name that shows instead of the public username in group chats
   - The display name is per-chat or global (implementation decision)
   - If no display name is set, the public username is shown
   - Display names do not need to be unique

4. **Identity in Group Chats:**
   - In group chat messages, users are identified by their display name (if set) or public username
   - This allows for clear attribution of messages in collaborative conversations
   - The system maintains a mapping between public usernames and user accounts for message synchronization

### Group Chat Message Flow

In group chat mode:

1. **User Sends Message:**
   - User types a message and sends it
   - Message is encrypted and stored with the user's public username/display name
   - Message is synced to all users who have access to the chat

2. **OpenMates Response Trigger:**
   - If the message contains **@OpenMates** mention:
     - Message is sent to LLM inference with full chat history
     - OpenMates generates a response
     - Response is encrypted and synced to all users in the group chat
   - If the message does not contain **@OpenMates** mention:
     - Message is treated as a regular human-to-human message
     - No LLM inference is triggered
     - Message remains visible to all group chat participants

3. **Message Synchronization:**
   - All messages (both user messages and OpenMates responses) are synchronized in real-time to all participants
   - Each participant sees the same conversation state
   - Message order is preserved across all participants

## Privacy and Security

- **URL Pattern:** Shared chat links use the format `/share/chat/{chat-id}#key={encryption-key}` where the chat ID is in the path (accessible to server for OG tag generation) and the encryption key is stored in the URL fragment (everything after the `#` symbol)
- **Server Privacy:** The URL fragment is never sent to the server - it remains entirely on the client side. This means the server never receives or sees the encryption key, ensuring maximum privacy. The server only sees the chat ID from the path, which is used for access control and OG tag generation
- **Search Engine Protection:** Shared chats are optimized for social media sharing via the `/share/chat/{chat-id}` path (without fragment), while the encryption key in the fragment ensures privacy for direct access
- **Zero-Knowledge Encryption:** All messages remain encrypted, even when shared

## Password Protection

Users can optionally set a password when sharing a chat or embed to add an additional layer of security. The password protection works as follows:

### Password-Based Key Blob Encryption

1. **Unified Encryption Approach:**
   - The key blob is **always** encrypted with a key derived from the chat ID: `KDF(chat_id) → derived_key`
   - The blob contains: `chat_encryption_key`, `generated_at`, `duration_seconds`, and `pwd` flag
   - **Without password:** `chat_encryption_key` is stored as plaintext in the blob, `pwd=0`
   - **With password:** `chat_encryption_key` is encrypted with password-derived key before being stored in the blob, `pwd=1`
   - The encrypted blob is stored in the URL: `/share/chat/{chat-id}#key={encrypted_blob}`
   - The `pwd` flag inside the blob tells the receiver: "This share requires a password"
   - **No server storage:** The server never stores any password-related information (no hash, no salt, no indication of password protection)

2. **Security Properties:**
   - **True Zero-Knowledge:** Server has no knowledge of password protection - it cannot distinguish between password-protected and non-password-protected shares
   - **No Server Storage:** No password hash, salt, or any password-related data is stored on the server
   - **Brute Force Protection:** Failed decryption attempts provide no feedback, making brute force attacks impractical
   - **Key Binding:** Password is cryptographically bound to the `chat_encryption_key`—changing the password invalidates decryption
   - **Time-Bound:** Duration is encrypted in the blob alongside the password flag, so both password and expiration are protected
   - **Consistent Architecture:** Always uses chat-ID-derived key for blob encryption, simplifying implementation

3. **Access Flow (Zero-Knowledge):**
   - When someone accesses a password-protected share via `/share/chat/{chat-id}#key={encrypted_blob}`:
     1. Client extracts `chat_id` from URL path and `key` from URL fragment
     2. Client derives key from chat ID: `KDF(chat_id) → derived_key`
     3. Client decrypts blob with chat-ID-derived key → extracts `chat_encryption_key` (may be encrypted), `generated_at`, `duration_seconds`, `pwd`
     4. Client checks `pwd` flag:
        - **If `pwd=0`:** `chat_encryption_key` is plaintext, proceed directly
        - **If `pwd=1`:** `chat_encryption_key` is encrypted, password required
     5. **If password required (`pwd=1`):**
        - Client prompts user: "This chat requires a password"
        - User enters password
        - Client derives key from password: `KDF(password) → password_derived_key`
        - Client attempts to decrypt `chat_encryption_key` with password-derived key
        - **If decryption succeeds:** Extract actual `chat_encryption_key` ✅
        - **If decryption fails:** Show error "Incorrect password. Please try again." and prompt retry
     6. **After obtaining `chat_encryption_key` (from step 4 or 5):**
        - Client sends request to server with `chat_id` (blob and key stay in fragment, never sent to server)
        - Server checks if chat exists and is shared, then returns encrypted content
        - Client fetches server time and validates: `server_time - generated_at ≤ duration_seconds`
        - If valid: Use `chat_encryption_key` to decrypt chat content
        - If expired: Show error "This chat link has expired"
        - Content is displayed ✅

4. **Comparison: With and Without Password**
   - **Without password:** Blob encrypted with `KDF(chat_id)`, `chat_encryption_key` is plaintext in blob, `pwd=0`—anyone with the link can decrypt the blob and access the chat
   - **With password:** Blob encrypted with `KDF(chat_id)`, `chat_encryption_key` is encrypted with `KDF(password)` before being stored in blob, `pwd=1`—anyone with the link can decrypt the blob, but only users with the password can decrypt the `chat_encryption_key` to access the chat
   - In both cases, the blob structure is identical: `{chat_encryption_key, generated_at, duration_seconds, pwd}`
   - The difference is whether `chat_encryption_key` is plaintext or password-encrypted inside the blob
   - The blob encryption key is always derived from the chat ID, ensuring consistent architecture

## Message Visibility Control

### Read-Only Mode (Public and User-Specific)

For read-only shared chats (both public and user-specific):

#### Initial Sharing (Read-Only)

When a chat is first shared in read-only mode:

- **All existing messages are shared:** When sharing is enabled, all messages up to the most recent one at that moment are immediately available to shared users
- The system records the timestamp of the most recent message at the time of sharing
- This timestamp defines the cutoff point for what shared users can access

#### Follow-up Messages

After sharing a chat in read-only mode:

- **New messages are private by default:** When the chat owner sends follow-up messages after sharing, these new messages are not automatically included in the shared version
- Shared users cannot see these newer messages until the owner explicitly updates the shared chat
- This gives the owner control over when to make new content visible to others

#### User Response Behavior

If a shared user attempts to respond to a read-only chat:

- The chat is automatically copied to the user's account
- The user's follow-up messages and assistant responses are only visible to that user
- The original shared chat remains unchanged and unaffected
- This ensures read-only shares remain stable and don't get cluttered with individual user interactions

#### Updating Shared Content

To include newer messages in a read-only shared chat:

- The chat owner clicks the "Update shared chat" button in the interface
- This action updates the timestamp cutoff point to include all messages up to the most recent one
- No new share link is needed - the existing link continues to work, but now shows the updated content
- The UI clearly indicates which messages are currently shared and which remain private

### Group Chat Mode (User-Specific Only)

For group chat mode (only available for user-specific sharing):

#### Initial Sharing (Group Chat)

When a chat is first shared in group chat mode:

- **All existing messages are shared:** All messages up to the most recent one at that moment are immediately available to all group chat participants
- All participants can see the full conversation history from the point of sharing

#### Follow-up Messages (Group Chat)

After sharing a chat in group chat mode:

- **All new messages are automatically synced:** When any participant (including the original owner) sends a message, it is immediately visible to all group chat participants
- **Real-time synchronization:** Messages are synchronized in real-time to all participants
- **No update button needed:** Unlike read-only mode, there is no "Update shared chat" button - all messages are automatically included as they are sent

#### Message Attribution

- Each message is attributed to the sender using their display name (if set) or public username
- All participants can see who sent each message
- OpenMates responses are clearly marked and only occur when **@OpenMates** is mentioned

## User Interface Requirements

The interface must provide clear visual feedback and controls for different sharing modes:

### UI Requirements for Read-Only Mode (Public and User-Specific)

- **Visual Boundary:** A clear divider or indicator showing where the shared portion ends
- **Message Status:** Users can easily see which messages are shared and which are private
- **Update Control:** An "Update shared chat" button allows owners to easily extend the shared portion to include more recent messages
- **Sync Status:** The interface shows which messages are synced with the shared version and allows owners to update the shared content
- **Response Warning:** When a user attempts to respond to a read-only chat, the UI should clearly indicate that their response will create a copy of the chat for their personal use

### UI Requirements for Group Chat Mode (User-Specific Only)

- **Participant List:** Display all participants in the group chat with their display names or public usernames
- **Real-time Sync Indicator:** Show when messages are being synchronized to other participants
- **@OpenMates Mentioning:** Clear UI indication that mentioning @OpenMates is required to trigger OpenMates responses
- **Message Attribution:** Each message clearly shows the sender's display name or public username
- **Public Username Setup:** When first enabling group chat mode, prompt the user to create a unique public username with clear instructions about uniqueness requirements
- **Display Name Management:** Allow users to set and update their display name for the group chat

### General Sharing UI

- **Sharing Mode Selection:** Clear options to choose between read-only and group chat modes (for user-specific sharing)
- **Password Protection Toggle:** Option to set an optional password for both public and user-specific sharing
- **Share Link Display:** Show the shareable link with clear copy-to-clipboard functionality
- **Access Control:** For user-specific sharing, show list of users who have access and allow adding/removing users

### Chat Context Menu Behavior for Shared Chats

The context menu (right-click or long-press on a chat in the sidebar) shows different actions based on the user's relationship to the chat:

#### For Chat Owner (Original Creator)
- **All sharing modes** (private, read-only, group chat, public):
  - Show **"Delete"** option - the owner can always delete the chat they created
  - Owner can remove their own chat from all devices and revoke access from all participants

#### For Shared Users (Read-Only Mode)
- **Read-only shared chats:**
  - Show **"Leave"** option instead of "Delete" - shared users cannot delete the owner's chat
  - Show **"Download"** and **"Copy"** options to export the shared content
  - Leaving a read-only shared chat removes it from the user's sidebar but doesn't delete the original chat

#### For Group Chat Participants
- **Group chat mode:**
  - Show **"Leave"** option instead of "Delete" - participants cannot delete the shared group chat
  - Show **"Download"** and **"Copy"** options to export the conversation
  - Leaving a group chat removes the user from participants and hides it from their sidebar
  - The user's historical messages remain visible to other participants

#### For Public Chat Viewers
- **Public shared chats (not started by user):**
  - Show **"Leave"** option instead of "Delete"
  - The chat can be downloaded or copied before leaving
  - Leaving hides the public chat from the user's sidebar (but it remains publicly accessible to others)

#### Context Menu Actions Available
- **Delete:** Only shown for chat owner (removes chat and all data)
- **Leave:** Shown for shared users and public chat viewers (removes from sidebar, doesn't delete)
- **Download:** Available to all users (exports chat as YAML)
- **Copy:** Available to all users (copies chat to clipboard as YAML with embedded link)
- **Select:** Entry point to multi-select mode for bulk operations

This design enables flexible, secure sharing while maintaining user control over privacy and message visibility.

## Additional Implementation Considerations

### Public Username Management

1. **Username Validation:**
   - Server must validate username uniqueness across all users before creation
   - Username format requirements (e.g., alphanumeric, length constraints) should be defined
   - Username changes after creation may be allowed or restricted (implementation decision)

2. **Username Lookup:**
   - System needs efficient lookup mechanism to resolve public usernames to user accounts
   - This is needed for message attribution and participant management in group chats

### Group Chat Participant Management

1. **Adding Participants:**
   - Chat owner can add new participants by email address
   - New participants receive email notification with access link
   - New participants must have a public username to participate (prompted on first access if needed)

2. **Removing Participants:**
   - Chat owner can remove participants from group chat
   - Removed participants lose access but their past messages remain visible (historical record)
   - Consider whether removed participants should be notified

3. **Participant Status:**
   - Track active/inactive participants
   - Consider showing "last seen" or online status indicators

### Mode Conversion

1. **Read-Only to Group Chat:**
   - Chat owner may want to convert a read-only shared chat to group chat mode
   - This should prompt for public username creation if not already set
   - Historical messages remain visible to all participants

2. **Group Chat to Read-Only:**
   - Chat owner may want to convert a group chat back to read-only mode
   - This stops new messages from being synced but preserves existing conversation
   - Consider whether to allow this conversion or require creating a new share

### Message Management in Group Chats

1. **Message Editing:**
   - Consider whether users can edit their messages in group chats
   - If allowed, edited messages should sync to all participants
   - Consider showing edit history or timestamps

2. **Message Deletion:**
   - Consider whether users can delete their messages in group chats
   - If allowed, deletion should sync to all participants
   - Consider soft-delete vs hard-delete options

3. **Message Ordering:**
   - Ensure consistent message ordering across all participants
   - Handle race conditions when multiple users send messages simultaneously
   - Use timestamps and conflict resolution strategies

### Error Handling and Edge Cases

1. **Username Conflicts:**
   - Handle race conditions when multiple users try to claim the same username
   - Provide clear error messages when username is already taken

2. **Network Failures:**
   - Handle cases where message synchronization fails
   - Implement retry mechanisms for failed syncs
   - Show clear error states to users

3. **Access Revocation:**
   - Handle cases where a user's access is revoked while they are viewing the chat
   - Gracefully handle encryption key changes or chat deletion

## Embed Sharing

Embeds (app skill results, files, code, etc.) can be shared both as part of shared chats and independently. See [Embeds Architecture](./embeds.md) for detailed information.

### Embed Decryption in Shared Chats

When a chat is shared, embedded content must also be decryptable by the recipient using the `chat_encryption_key` from the share link. This is achieved through the **wrapped key architecture**:

**How It Works:**
1. Each embed has a unique `embed_key` that encrypts its content
2. The `embed_key` is stored in multiple wrapped forms in the `embed_keys` collection:
   - `key_type="master"`: `AES(embed_key, master_key)` - for owner's cross-chat access
   - `key_type="chat"`: `AES(embed_key, chat_key)` - one per chat the embed is referenced in
3. When chat is shared, recipient uses `chat_encryption_key` to unwrap `embed_key` from the `key_type="chat"` entry
4. Recipient uses `embed_key` to decrypt embed content

**Offline-First Sharing:**
- All wrapped keys are pre-stored on server when embed is created/copied to chat
- No server request needed at share time - sharer already has `chat_encryption_key`
- Share link contains `chat_encryption_key` in encrypted blob (URL fragment)

**Access Flow for Shared Chat Embeds:**
1. Recipient opens shared chat link, extracts `chat_encryption_key` from URL fragment
2. Client fetches chat and embeds from server
3. For each embed, client queries `embed_keys` by `hashed_embed_id` and `hashed_chat_id`
4. Client unwraps `embed_key`: `AES_decrypt(encrypted_embed_key, chat_encryption_key)`
5. Client decrypts embed content: `AES_decrypt(encrypted_content, embed_key)`
6. Embed is displayed ✅

### Independent Embed Sharing

Embeds can also be shared independently of any chat:

**URL Pattern**: `/share/embed/{embed-id}#key={encrypted_blob}`
- Encrypted blob contains: `embed_key`, `generated_at`, `duration_seconds`, `pwd` flag
- Blob encrypted with key derived from embed_id: `KDF(embed_id) → derived_key`
- Server only sees `embed_id` from path (fragment never sent to server)

**Access Flow:**
1. Client extracts `embed_id` from URL path and encrypted blob from URL fragment
2. Client derives decryption key from embed_id: `KDF(embed_id) → derived_key`
3. Client decrypts blob → extracts `embed_key`, `generated_at`, `duration_seconds`, `pwd` flag
4. If `pwd=1` (password protected): prompt for password, derive password key, decrypt `embed_key`
5. Client sends request to server with `embed_id` to fetch encrypted content
6. Server checks `share_mode` and returns encrypted content if allowed
7. Client decrypts content using `embed_key`
8. Content is displayed ✅

**Access Control:**
- Server checks `share_mode` ('private', 'shared_with_user', 'public') and `shared_with_users` array
- If `share_mode === 'public'`: Return encrypted content
- If `share_mode === 'shared_with_user'`: Check if user's `hashed_user_id` is in `shared_with_users` array
- If `share_mode === 'private'`: Return error

### Differences from Chat Sharing

- **Independent of Chats**: Embeds can be shared without sharing the entire chat
- **No Message Visibility Control**: Embeds are shared as complete entities (no timestamp-based cutoff)
- **Cross-Chat References**: Shared embeds can be referenced in multiple chats

## Database Schema for Sharing Metadata

### Problem Statement

For social media sharing (OG tags), the server needs to be able to read chat/embed metadata (title, summary) to generate previews. However, the current architecture uses client-side encryption (zero-knowledge), where fields like `encrypted_title` and `encrypted_chat_summary` are encrypted with user-specific keys that the server cannot decrypt.

### Solution: Vault-Encrypted Shared Metadata Fields

Add new vault-encrypted fields to the database schema that are only populated when sharing is enabled. These fields use a **shared vault key** (not user-specific) so the server can decrypt them for OG tag generation without needing user context.

### Database Schema Changes

#### Chats Collection

Add the following fields to the `chats` collection:

- `shared_encrypted_title` (text, nullable)
  - Vault-encrypted title using shared vault key
  - Only populated when `share_mode` is enabled
  - Server can decrypt for OG tag generation

- `shared_encrypted_summary` (text, nullable)
  - Vault-encrypted chat summary using shared vault key
  - Only populated when `share_mode` is enabled
  - Server can decrypt for OG tag generation

#### Embeds Collection

Add the following fields to the `embeds` collection:

- `shared_encrypted_title` (text, nullable)
  - Vault-encrypted title/description using shared vault key
  - Only populated when `share_mode` is not 'private'
  - Server can decrypt for OG tag generation

- `shared_encrypted_description` (text, nullable)
  - Vault-encrypted description/preview using shared vault key
  - Only populated when `share_mode` is not 'private'
  - Server can decrypt for OG tag generation

### Shared Vault Key

- **Key Name**: `shared-content-metadata` (or similar)
- **Purpose**: Encrypt/decrypt metadata for all shared chats and embeds
- **Access**: Server has access via Vault (not user-specific)
- **Benefits**:
  - Works for public shares (no user context needed)
  - Fast OG tag generation (no user lookup required)
  - Simple: one key for all shared metadata
  - Secure: still vault-encrypted, just not user-specific

### Sharing Flow

1. **User Initiates Sharing**:
   - Client decrypts `encrypted_title` and `encrypted_chat_summary` using chat key (derived from master key)
   - Client sends plaintext title and summary to server (only when sharing is enabled)
   - Server has `is_private = false` by default

2. **Server Stores Shared Metadata**:
   - Server encrypts title and summary with shared vault key (`shared-content-metadata`)
   - Server stores encrypted values in `shared_encrypted_title` and `shared_encrypted_summary`
   - Original `encrypted_title` and `encrypted_chat_summary` remain unchanged (zero-knowledge preserved)

3. **OG Tag Generation**:
   - Server receives request for `/share/chat/{chat-id}` (no user context needed)
   - Server looks up chat by `chat_id`
   - If chat doesn't exist: Server returns deterministic dummy data (prevents enumeration)
   - If chat exists and `is_private = true`: Server returns dummy data (chat was unshared)
   - If chat exists and `is_private = false`: Server decrypts `shared_encrypted_title` and `shared_encrypted_summary` using shared vault key
   - Server generates OG tags with decrypted metadata (or dummy data if chat is private/non-existent)

4. **Updating Shared Metadata**:
   - When chat title or summary changes, if chat is shared (`is_private = false`), update `shared_encrypted_*` fields
   - Client sends updated plaintext metadata → Server re-encrypts with shared vault key
   - This update is queued if offline and retried when connection is restored

5. **Unsharing a Chat**:
   - User clicks "Unshare" in the Shared settings menu
   - Client sends request to server to set `is_private = true`
   - Server updates `is_private` field to `true`
   - **Server MUST clear `shared_encrypted_title` and `shared_encrypted_summary`** (set to null) to remove OG metadata
   - Existing share links become invalid (server returns dummy data for `is_private = true` chats)
   - Users who had access via share links will lose access on next login/tab reload (client checks `is_private` field)

6. **Checking for Unshared Chats**:
   - On login and tab reload, client checks all chats where user is not the owner
   - For each shared chat, client requests `is_private` status from server
   - If `is_private = true`, client removes the chat from local storage and UI
   - This ensures users don't retain access to chats that have been unshared

### Security Model for Offline Sharing

**Why `is_private` defaults to `false`:**
- Enables true offline sharing - users can generate share links without server contact
- Share link generation happens entirely client-side using the chat encryption key
- No server request needed to create a shareable link

**Security protections:**
1. **Chat ID obfuscation**: Chat IDs are UUIDs, making them extremely difficult to guess
2. **Encryption key requirement**: Even with a valid chat ID, the encryption key (in URL fragment) is required to decrypt content
3. **Dummy data for non-existent chats**: Server returns realistic-looking dummy data for any chat ID that doesn't exist, preventing enumeration
4. **Rate limiting**: `/share/chat/{chat-id}` endpoint is rate-limited to prevent brute force attempts
5. **Unshare protection**: When `is_private = true`, server returns dummy data, making share links invalid

**Access flow:**
- User with share link: Has both chat ID (in path) and encryption key (in fragment)
- Server sees only chat ID (fragment never sent to server)
- Server returns encrypted data if `is_private = false` and chat exists
- Client decrypts using key from fragment
- Without correct key, encrypted data is useless

### Privacy Considerations

- **Zero-Knowledge Maintained**: Original `encrypted_title` and `encrypted_chat_summary` fields remain client-encrypted and unchanged
- **Shared Metadata Only**: New vault-encrypted fields only exist when sharing is enabled
- **Clear Separation**: Private metadata (client-encrypted) vs. shared metadata (vault-encrypted)
- **No User Context Needed**: Shared vault key allows OG tag generation without user lookup

### Benefits

- **Works for Public Shares**: No user context required for OG tag generation
- **Fast Performance**: Direct decryption without user lookup
- **Simple Architecture**: One shared key for all shared content
- **Maintains Privacy**: Original zero-knowledge fields remain untouched

## Social Media Sharing & Hosting Considerations

### Social Media Optimization (OG Tags)

Shared chats and embeds need to be optimized for social media platforms (WhatsApp, iMessage, Twitter, Facebook, etc.) which require Open Graph (OG) meta tags for rich previews. However, URL fragments (hash-based URLs) are not accessible to social media crawlers, requiring a hybrid URL approach.

### URL Structure for Social Sharing

**Public-facing URL (for social crawlers):**

```text
/share/chat/{chat-id}
/share/embed/{embed-id}
```

**Full access URL (with encryption key):**

```text
/share/chat/{chat-id}#key={encryption-key}
/share/embed/{embed-id}#key={encryption-key}
```

**Final redirect URL (main app):**

```text
/#chat-id={chat-id}&key={encryption-key}
/#embed-id={embed-id}&key={encryption-key}
```

### Implementation Requirements

1. **Server Route for OG Tags**: A server route at `/share/chat/{chat-id}` must serve HTML with OG meta tags when accessed without a key fragment
2. **Client-Side Redirect**: When accessed with a key fragment, the page redirects to the main app URL
3. **OG Image Selection**: Server selects predefined OG images based on chat category (for chats) or app skill/embed type (for embeds)
4. **Metadata Endpoint**: Backend API endpoint that returns public metadata (encrypted title, summary) for OG tag generation

### Hosting Migration Considerations

The sharing feature requires server-side routes (`+server.ts` in SvelteKit) to serve OG tags. The implementation must be portable across hosting providers.

#### Current Setup (Vercel)

- Uses `@sveltejs/adapter-vercel` which supports serverless functions
- Server routes automatically run on Vercel's serverless infrastructure
- No additional configuration needed

#### Migration Options

##### Option 1: Node.js Adapter (Recommended for VM hosting)

- Switch to `@sveltejs/adapter-node` for traditional Node.js server
- Runs as a Node.js process on your VM
- Requires reverse proxy (Nginx) configuration
- Full control over server environment
- Works with Docker containers

##### Option 2: Static Adapter + Backend API

- Use `@sveltejs/adapter-static` for frontend
- Move server routes to FastAPI backend
- Serve OG tags via FastAPI endpoints
- Nginx routes `/share/*` to FastAPI, static files to CDN
- Clean separation of concerns

##### Option 3: Docker Container

- Containerize Node.js app with adapter-node
- Deploy alongside existing backend services
- Use docker-compose for orchestration
- Consistent deployment across environments

### Code Portability Principles

To ensure easy migration between hosting providers:

1. **Avoid Platform-Specific APIs**: Use only standard SvelteKit APIs in server routes
2. **Abstract Environment Variables**: Use config abstraction layer, not direct `process.env` access
3. **Keep Server Routes Simple**: Server routes only serve static HTML with OG tags - no heavy operations
4. **Static Asset Serving**: Predefined OG images are served as static assets, compatible with any hosting provider
5. **No Platform-Specific Dependencies**: Avoid platform-specific packages (e.g., `@vercel/og`) - use static images instead

### OG Image Strategy

To simplify implementation and reduce complexity, OG images use a predefined set of static images rather than generating them dynamically for each shared chat or embed.

#### For Shared Chats

- **Image Selection**: One predefined OG image per mate category (e.g., `software_development`, `business_development`, `medical_health`, etc.)
- **Mapping**: Server determines chat category from the chat's metadata and selects the corresponding predefined image
- **Fallback**: If category is unknown or missing, use a default OG image for general chats
- **Storage**: Predefined images stored as static assets (e.g., `/static/og-images/category-{category-name}.png`)
- **Benefits**:
  - No image generation overhead
  - Fast serving (static files)
  - Consistent branding per category
  - Simple to maintain and update

#### For Shared Embeds

- **Image Selection**: One predefined OG image per app skill or embed type (e.g., `web.read` for app skills, `website` for website embeds, `code` for code embeds, `file` for file embeds, etc.)
- **Mapping**: Server determines embed type (app skill or content embed type) from embed metadata and selects the corresponding predefined image
- **Fallback**: If embed type is unknown or missing, use a default OG image for general embeds
- **Storage**: Predefined images stored as static assets (e.g., `/static/og-images/embed-{embed-type}.png` or `/static/og-images/skill-{app-id}-{skill-id}.png` for app skills)
- **Benefits**:
  - No image generation overhead
  - Fast serving (static files)
  - Consistent branding per embed type
  - Simple to maintain and update

#### OG Title and Description

While OG images are predefined, the **OG title and description remain specific to each chat/embed**:

- **Title**: Server decrypts `shared_encrypted_title` using shared vault key and uses it for `og:title`
- **Description**: Server decrypts `shared_encrypted_summary` (for chats) or `shared_encrypted_description` (for embeds) using shared vault key and uses it for `og:description`
- **Personalization**: Each shared chat/embed gets unique, descriptive title and description while using category/skill-appropriate images

#### Future Enhancement

This simplified approach can be enhanced later to generate custom OG images per chat/embed if needed, but the predefined approach provides:

- Immediate implementation without complex image generation
- Fast performance (no generation overhead)
- Consistent visual branding
- Easy maintenance

### Access Flow with Social Sharing

1. **Social Crawler Access**: Hits `/share/chat/{chat-id}` (no fragment) → Server returns HTML with OG tags → Crawler extracts preview for social media platforms
2. **User Click**: Opens `/share/chat/{chat-id}#key={encryption-key}` → Client-side JavaScript detects the key fragment and redirects to main app URL format: `/#chat-id={chat-id}&key={encryption-key}`
3. **Main App**: Loads chat, extracts `chat-id` and `key` from URL fragment, decrypts and displays content

### Privacy Maintained

- Encryption key remains in URL fragment (never sent to server)
- Server only sees `chat-id` or `embed-id` (non-sensitive identifiers)
- OG tags generated from encrypted metadata only (no content decryption)
- Zero-knowledge architecture preserved
