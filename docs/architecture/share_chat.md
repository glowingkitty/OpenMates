# Share chat architecture

> **Note:** This feature is not yet implemented. This document describes the planned architecture.
>
> **For technical details:** See the [database schema](../../backend/core/directus/schemas/chats.yml) for field names and data structure.

## Overview

The share chat feature allows users to share their conversations with other users or make them publicly accessible. All shared chats remain encrypted, ensuring privacy even when shared.

## Sharing Options

### Share with Public

When sharing publicly:

1. **Sharing Process:**
   - The chat owner clicks "Share public" to make the chat publicly accessible
   - A shareable link is generated with the format: `/share/chat/{chat-id}#key={encryption-key}` where the chat ID is in the path and the encryption key is stored in the URL fragment (after the `#`)
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
   - When someone accesses a shared chat via `/share/chat/{chat-id}#key={encryption-key}`:
     1. Client extracts `chat_id` from URL path and `key` from URL fragment
     2. Client sends request to server with `chat_id` (key stays in fragment, never sent to server)
     3. Server checks if chat exists and is shared, then returns encrypted content
     4. Client-side JavaScript redirects to main app URL format: `/#chat-id={chat-id}&key={encryption-key}` for final rendering
     5. Client attempts to decrypt content using `shared_encryption_key` from URL fragment
     6. **If decryption succeeds:** Content is displayed ✅
     7. **If decryption fails:**
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

Embeds (app skill results, files, code, etc.) can be shared independently of chats using the same zero-knowledge architecture. See [Embeds Architecture](./embeds.md) for detailed information.

### Key Similarities

- **URL Pattern**: Shared embed links use the format `/share/embed/{embed-id}#key={shared_encryption_key}` where the embed ID is in the path and the encryption key is stored in the URL fragment
- **Server Privacy**: The URL fragment is never sent to the server - it remains entirely on the client side. The server only sees the embed ID from the path
- **Zero-Knowledge Encryption**: All embed content remains encrypted, even when shared
- **Access Control**: Server checks `share_mode` ('private', 'shared_with_user', 'public') and `shared_with_users` array for access control

### Access Flow

When someone opens a shared embed link via `/share/embed/{embed-id}#key={shared_encryption_key}`:

1. Client extracts `embed_id` from URL path and `key` from URL fragment
2. Client sends request to server with `embed_id` (key stays in fragment, never sent to server)
3. Server checks:
   - Does embed exist?
   - If `share_mode === 'public'`: Return encrypted content
   - If `share_mode === 'shared_with_user'`: Check if user's `hashed_user_id` is in `shared_with_users` array
     - If yes: Return encrypted content
     - If no: Return error
   - If `share_mode === 'private'`: Return error
4. If access granted: Server returns encrypted content (server has no knowledge of password protection)
5. Client-side JavaScript redirects to main app URL format: `/#embed-id={embed-id}&key={shared_encryption_key}` for final rendering
6. Client attempts to decrypt content using `shared_encryption_key` from URL fragment
7. **If decryption succeeds:** Content is displayed ✅
8. **If decryption fails:**
   - Client prompts user: "Unable to decrypt. If this share is password-protected, enter the password:"
   - User enters password (if applicable)
   - Client derives key from password (using deterministic salt or client-stored salt)
   - Client combines password-derived key with `shared_encryption_key` from URL fragment
   - Client attempts decryption again with combined key
   - If decryption succeeds: Content is displayed ✅
   - If decryption still fails: Show error: "Unable to decrypt. Please verify the link and password (if required)."
9. If access denied or embed doesn't exist: Show unified error message: "Embed can't be found. Either it doesn't exist or you don't have access to it."

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

2. **Server Stores Shared Metadata**:
   - Server encrypts title and summary with shared vault key (`shared-content-metadata`)
   - Server stores encrypted values in `shared_encrypted_title` and `shared_encrypted_summary`
   - Original `encrypted_title` and `encrypted_chat_summary` remain unchanged (zero-knowledge preserved)

3. **OG Tag Generation**:
   - Server receives request for `/share/chat/{chat-id}` (no user context needed)
   - Server looks up chat by `chat_id`
   - Server decrypts `shared_encrypted_title` and `shared_encrypted_summary` using shared vault key
   - Server generates OG tags with decrypted metadata

4. **Updating Shared Metadata**:
   - When chat title or summary changes, if chat is shared, update `shared_encrypted_*` fields
   - Client sends updated plaintext metadata → Server re-encrypts with shared vault key

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
