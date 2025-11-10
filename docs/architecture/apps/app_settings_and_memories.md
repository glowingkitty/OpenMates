# App Settings and Memories

## Overview

App settings and memories are user-specific data stored per app (e.g., watched movies and TV shows for TV app, favorite restaurants for Maps app, upcoming trips for Travel app). Each **entry** within a settings/memories category (e.g., individual movie, restaurant, or trip) is stored as an encrypted item in Directus for scalability and efficient sync.

**Storage Model**: Per entry per settings/memories category for a specific user and app. For example:

- `tv` app, `watched_movies` category: Multiple entries (one per movie)
- `tv` app, `favorite_shows` category: Multiple entries (one per show)
- `maps` app, `favorite_restaurants` category: Multiple entries (one per restaurant)

App settings and memories schemas are defined in each app's `app.yml` file (e.g., `backend/apps/tv/app.yml`). The structure defines which settings/memories an app supports and their data types.

For encryption architecture, see [security.md#app-settings--memories](../security.md#app-settings--memories).

## Client-Side Interaction

![App settings and memories](../../images/apps/request_app_settings_memories.png)

As described in [message_processing.md](../message_processing.md), the client submits an overview of the type of app settings and memories that are available. The assistant then requests the data from the user via WebSocket connection, and the app settings & memories show up in chat history as a JSON code block containing included categories with their values and excluded categories without values.

## Connected Accounts

Some apps require connecting external accounts to access their services. These connected accounts are managed within the app's settings and memories section in the App Store.

### Purpose

Connected accounts allow apps to interact with external services on your behalf. For example:

- **Figma**: Connect your Figma account to access design files and projects
- **Gmail**: Connect your Gmail account to send and manage emails
- **Calendar services**: Connect Google Calendar, Cal.com, or other calendar providers
- **Other services**: Various apps may require connections to external APIs

### Connection Methods

Apps support two methods for connecting accounts:

1. **OAuth 2.0**: Secure, token-based authentication that doesn't require sharing passwords
   - User is redirected to the service provider's login page
   - User grants permissions to OpenMates
   - Access tokens are securely stored (encrypted server-side using Vault)
   - Tokens can be revoked at any time

2. **API Key**: Direct API key authentication for services that support it
   - User provides their API key from the external service
   - API key is encrypted server-side using Vault before storage
   - Keys can be updated or removed at any time

### Managing Connected Accounts

Connected accounts are managed in the App Store:

- **View connections**: See all connected accounts for each app in the app's detail view
- **Add connection**: Connect new accounts via OAuth flow or API key entry
- **Revoke access**: Disconnect accounts at any time, which immediately revokes access
- **Update credentials**: Refresh OAuth tokens or update API keys when needed

### Privacy and Security

**Encryption Model**: Server-side encryption with HashiCorp Vault (similar to credit balance and 2FA secrets)

- **Token Storage**: OAuth tokens and API keys are encrypted using per-user Vault keys
- **Server Access**: Server can decrypt tokens when needed for processing requests (enables offline processing)
- **Operation-Based Security**: Different security levels based on operation type and access method:
  - **Read-only operations**: Automatic server access (e.g., reading calendar events, fetching Figma files, reading emails)
  - **Write operations**:
    - **Web App**: Require user confirmation via WebSocket by default. Can be auto-confirmed if Autonomous Mode is enabled (unless skill has "Always Require Confirmation" override). Users can configure per-skill confirmation requirements in App Store settings.
    - **REST API/CLI**: No confirmation required by default, but protected by multiple security layers: API key scopes/permissions, rate limiting, privacy-compliant logging, device confirmation, and optional Enhanced Security Mode (requires confirmation for all API actions when enabled)
  - **High-risk operations**:
    - **Web App**: Always require explicit user confirmation with extended timeout, unless Autonomous Mode is enabled and skill doesn't have "Always Require Confirmation" override
    - **REST API/CLI**: No confirmation required by default, but heavily rate-limited, logged, and protected by all security layers. Optional Enhanced Security Mode can require confirmation for these operations

**User Control**:

- **Connection Preferences**: Users can configure per-connection security settings (e.g., "Allow automatic calendar reads but require confirmation for writes")
- **Access Logging**: All token usage is logged and visible to users in Developer Settings
- **Revocation**: Users can revoke access at any time, immediately invalidating tokens
- **Transparency**: Users see which operations require confirmation vs. automatic access
- **Enhanced Security Mode** (optional): Users can enable "Require confirmation for all API actions" in Developer Settings, which applies web app confirmation flow to REST API/CLI access

For detailed information on action confirmation architecture, see [Action Confirmation Architecture](./action_confirmation.md).

**Security Benefits**:

- Tokens encrypted at rest using Vault (same security model as credits/2FA)
- Server can process requests when user is offline (practical functionality for scheduled tasks, automated workflows)
- Operation-based controls prevent unauthorized high-risk actions
- User maintains full control through preferences and revocation
- All access is auditable and transparent

### App Store Display

In the App Store, apps that support connected accounts show:

- Which external services can be connected
- What permissions or access levels are required
- Connection status (connected/not connected) for each service
- Quick access to manage connections

## Versioning & Multi-Device Sync

Each app settings/memories item has an `item_version` field (integer, starts at 1) that increments on every update. This enables conflict detection and sync coordination across multiple devices.

### Version Tracking

- **item_version**: Integer that increments each time an item is updated
- **updated_at**: Unix timestamp of the last modification
- Maintained entirely by the client; server stores but doesn't increment

## Settings/Memories Management via Skills

Users can create, update, and delete settings/memories entries through the assistant's responses and follow-up confirmations. This is implemented as dynamically generated skills that are treated like any other app skill.

### Dynamic Skill Generation

For each settings/memories category defined in an app's `app.yml`, three dedicated skills are automatically generated using the naming conventions:

- `{app_id}.settings_memories_add_{category_name}` - Create new entries
- `{app_id}.settings_memories_update_{category_name}` - Update existing entries
- `{app_id}.settings_memories_delete_{category_name}` - Delete existing entries

Each skill includes:

- **Metadata**: app_id, category_name, display_name, description, and version (inherited from app)
- **Input Schema**:
  - **Add**: Extracted from the category's data schema in `app.yml`, including required and optional fields
  - **Update**: Includes `entry_id` (required) plus any fields from the category schema that should be updated (all optional)
  - **Delete**: Includes `entry_id` (required) for identifying the entry to delete
- **Output Schema**: Returns success status, entry_id (for add/update), and confirmation message

Skills are generated at backend startup, when app schemas change, or dynamically during main-processing when needed for a specific request.

### Execution Flow

**For Add Operations:**

1. **Post-Processing Suggestion**: Assistant suggests saving data to settings/memories based on conversation context, including rationale and confidence score.
2. **User Confirmation**: User confirms in a follow-up message, optionally providing additional details about what should be saved.
3. **Main-Processing Skill Execution**: LLM receives user confirmation, extracts structured data, and calls the `{app_id}.settings_memories_add_{category_name}` skill with complete data.
4. **Skill Handler Execution**: Handler validates data against category schema, generates entry_id and metadata (timestamp, version starts at 1), and sends plaintext entry data to client via WebSocket.
5. **Client Encryption**: Client receives plaintext entry data, encrypts it using app-specific encryption key (following zero-knowledge architecture), and sends encrypted data back to server for storage.
6. **Server Storage**: Server stores encrypted entry in Directus, updates AI cache, and returns success response.
7. **Success Response**: User receives confirmation, and the entry becomes available for future preprocessing requests, follow-up suggestions, and personalization.

**For Update Operations:**

1. **User Request**: User requests to update an existing entry (e.g., "Update my rating for Inception to 9.0" or "Change the notes on that restaurant").
2. **Entry Identification**: LLM identifies the relevant entry from conversation context or by asking the user to clarify which entry to update.
3. **Main-Processing Skill Execution**: LLM extracts the entry_id and updated fields, then calls the `{app_id}.settings_memories_update_{category_name}` skill.
4. **Skill Handler Execution**: Handler validates entry_id exists and belongs to user, validates updated fields against category schema, generates updated entry data with incremented item_version, and sends plaintext updated entry data to client via WebSocket.
5. **Client Encryption**: Client receives plaintext updated entry data, encrypts it using app-specific encryption key (following zero-knowledge architecture), and sends encrypted data back to server for storage.
6. **Server Storage**: Server stores encrypted updated entry in Directus, updates AI cache, and returns success response.
7. **Success Response**: User receives confirmation of the update.

**For Delete Operations:**

1. **User Request**: User requests to delete an existing entry (e.g., "Remove Inception from my watched movies" or "Delete that restaurant").
2. **Entry Identification**: LLM identifies the relevant entry from conversation context or by asking the user to clarify which entry to delete.
3. **Main-Processing Skill Execution**: LLM extracts the entry_id and calls the `{app_id}.settings_memories_delete_{category_name}` skill.
4. **Skill Handler Execution**: Handler validates entry_id exists and belongs to user, deletes entry from Directus, updates AI cache, and returns success response.
5. **Success Response**: User receives confirmation of the deletion.

**Note**: Delete operations do not require client-side encryption since only the entry_id is needed for deletion. The server can delete the encrypted entry directly from Directus without needing to decrypt it.

### Integration Points

**Pre-Processing**: Lists available settings/memories categories and skills (add, update, delete) for relevant apps, identifies which existing entries might be relevant, and requests content from client.

**Main-Processing**: Includes relevant settings/memories skills (add, update, delete) when apps are relevant to the request, making them available for LLM to call after user confirmation or when user requests modifications.

**Post-Processing**: Analyzes assistant response and conversation to suggest which data should be saved, updated, or deleted, references the appropriate skill (add/update/delete), includes confidence and rationale, and filters out suggestions that don't add unique value.

**Follow-up Suggestions**: Acknowledges newly-created, updated, or deleted entries, uses saved data in personalized suggestions, and suggests related actions based on the changes.

### Implementation Considerations

**Schema Validation**:

- **Add**: Input data is validated against category schema before storage, with helpful error messages for missing required fields.
- **Update**: Updated fields are validated against category schema, with validation only on provided fields (partial updates supported).
- **Delete**: Entry_id is validated to ensure it exists and belongs to the user.

**Deduplication**: System checks for duplicate entries before creating, considering exact matches and fuzzy matching, with user confirmation when duplicates are detected. For updates, system verifies entry exists and belongs to user.

**Error Handling**:

- Validation errors return success status, error message, and suggestion.
- Duplicate detection includes existing entry reference and update suggestion.
- Update/delete operations return clear error messages if entry not found or access denied.

**Performance**: Skill execution is optimized for sub-second response times, with cached skill definitions to avoid regeneration and support for batch operations when multiple entries are created, updated, or deleted in the same request.

### Data Model

Each settings/memories entry includes: entry_id (UUID), app_id, category, user_id, encrypted_data, created_at, updated_at, item_version (starts at 1), and chat_id (reference to where it was created).

**Encryption Flow**: Entries follow a zero-knowledge architecture similar to new chat suggestions:

1. **Server generates** entry data (plaintext) during skill execution
2. **Server sends** plaintext entry data to client via WebSocket
3. **Client encrypts** entry using app-specific encryption key (see [security.md#app-settings--memories](../security.md#app-settings--memories))
4. **Client sends** encrypted data back to server for storage in Directus
5. **Server stores** only encrypted data (zero-knowledge permanent storage)

This ensures the server never has access to plaintext entry contents, maintaining the same zero-knowledge security model as other user data.

## Security Considerations

**Encryption**: All entries are encrypted client-side before storage in Directus. The server generates entry data during skill execution and sends it to the client via WebSocket (plaintext). The client then encrypts the entry using the app-specific encryption key and sends the encrypted data back to the server for storage. Client manages all decryption keys, and server cannot access entry contents without the client providing decrypted data (zero-knowledge architecture).

**Validation**: All input is validated against schema, with rejection of malicious data (e.g., oversized entries, invalid formats) and rate limiting on skill execution to prevent abuse.

**Privacy**: Entries are per-user and per-app with no cross-app data sharing unless explicitly designed, following the same privacy model as regular settings/memories.