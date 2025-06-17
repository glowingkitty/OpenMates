# Chat Sync Architecture (Hybrid Model)

This document outlines the high-performance, real-time synchronization architecture for the chatbot application. The primary goals are to drastically reduce server requests, improve perceived client-side performance, and create a robust, scalable system by combining timestamp-based queries with version-based conflict resolution.

## Table of Contents

1.  [Core Principles](#1-core-principles)
2.  [Data Models & Prerequisites](#2-data-models--prerequisites)
3.  [The Hybrid Sync Flow](#3-the-hybrid-sync-flow)
    *   [Phase 1: Initial Connection & High-Priority Load](#phase-1-initial-connection--high-priority-load)
    *   [Phase 2: Main Background Delta Sync](#phase-2-main-background-delta-sync)
    *   [Phase 3: Ongoing Real-Time Updates](#phase-3-ongoing-real-time-updates)
4.  [Server-Side Caching Strategy](#4-server-side-caching-strategy)
5.  [Client-Side State Management](#5-client-side-state-management)

---

## 1. Core Principles

*   **Single Source of Truth:** The server (and by extension, Directus) is the single source of truth. The client's local state is a replica.
*   **Hybrid Sync:** Use timestamps (`updated_at`) for efficient initial data fetching and version numbers (`messages_v`, `title_v`, etc.) for robust, conflict-free data merging.
*   **Request Batching:** Eliminate N+1 query problems by fetching data in large, efficient batches.
*   **Perceived Performance First:** Prioritize loading the content the user is most likely to interact with first (their last-opened chat).
*   **Single WebSocket Connection:** Use one persistent WebSocket connection per client for all real-time communication to reduce overhead.

## 2. Data Models & Prerequisites

The following fields are required in the Directus models for this architecture to function correctly.

*   **`users` Model:**
    *   `last_opened`: A string field storing the last path, e.g., `/chat/CHAT_ID_HERE`. The server will parse the ID from this path to determine the initial chat to load on a fresh session.

*   **`chats` Model:**
    *   `id`: Standard primary key.
    *   `hashed_user_id`: Hashed relation to the user who owns the chat.
    *   `created_at`: Unix timestamp.
    *   `updated_at`: Unix timestamp that updates whenever the record or its direct relations (like a new message) are changed. **(Crucial for timestamp syncs)**.
    *   `messages_version`, `title_version`, etc.: Integer versions for granular, conflict-free updates.

*   **`messages` Model:**
    *   `id`: Standard primary key.
    *   `chat_id`: Relation to the parent chat.
    *   `hashed_user_id`: Hashed relation to the user who owns the message.
    *   `created_at`: Unix timestamp.
    *   `updated_at`: Unix timestamp that automatically updates whenever the record is changed. **(Crucial for timestamp syncs)**.

## 3. The Hybrid Sync Flow

The entire process, from app launch to a fully synced and interactive state.

### Phase 1: Initial Connection & High-Priority Load

*Goal: Display the user's last active chat on screen almost instantly.*

1.  **Client Connects & Authenticates:**
    *   The client opens a single WebSocket connection.
    *   It sends an `initial_sync_request` message containing its authentication token, `last_sync_timestamp`, and its map of known chat versions.

2.  **Server Identifies Active Chat:**
    *   The server validates the token and identifies the user.
    *   It parses the `chat_id` from the user's `last_opened` field. This determines the initial chat to load for a fresh session.

3.  **Server Fetches Active Chat Data:**
    *   Using the parsed `chat_id`, the server makes **one high-priority query** to its "Hot" cache or Directus to fetch that specific chat's full metadata AND all of its associated messages.

4.  **Server Pushes Active Chat to Client:**
    *   The server immediately sends an `active_chat_load` message over the WebSocket. This message contains the full data for the single active chat.
    *   The client receives this and immediately renders the chat view, making the app feel responsive.

### Phase 2: Main Background Delta Sync

*Goal: Efficiently and accurately sync all other chats.*

This phase runs in parallel or immediately after Phase 1.

1.  **Initial Timestamp Query:**
    *   The server makes **one efficient query** to the database.
    *   **Query:** Get all chats and messages for the user where `updated_at` > `last_sync_timestamp`. This quickly fetches a small superset of all possible changes.

2.  **Granular Version Comparison:**
    *   The server iterates through the results from the timestamp query.
    *   For each item, it compares its current version number on the server with the version number provided by the client.
    *   An item is only added to the final response if `server_version > client_version`.

3.  **Server Pushes Batched Sync Data:**
    *   The server assembles a `delta_sync_data` payload containing only the items that passed the version check. This payload includes:
        *   An array of updated chat metadata.
        *   An array of updated messages.
        *   A list of chat IDs to delete on the client.
        *   A new `server_timestamp` for the client to save. **This timestamp acts as a "high-water mark" for the next sync, allowing the server to efficiently query only for changes that have occurred since this moment.**

4.  **Client Processes Batch:**
    *   The client receives the single `delta_sync_data` message.
    *   It performs a **bulk-write** operation to update its IndexedDB.
    *   It saves the new `server_timestamp`.

### Phase 3: Ongoing Real-Time Updates

*Goal: Keep the client state perfectly in sync with small, lightweight messages after the initial sync. This logic is device-specific.*

1.  **Device-Specific Active Chat:**
    *   Each connected device (e.g., laptop, phone) maintains its own "active chat" state on the server's `ConnectionManager`.
    *   When a user sends a message, the client also sends a `set_active_chat` message. This updates the server's record for that specific device *only*.
    *   This ensures that real-time streaming updates are only sent to the device where the chat is actively being viewed. The `last_opened` field in the `users` table is only updated to persist the very last active chat across sessions, but does not dictate real-time behavior.

2.  **Differentiated Update Delivery:**
    *   **For the Active Device/Chat:** When an assistant is generating a response, the server streams paragraph-by-paragraph updates (`ai_message_update`) to the specific device that has that chat open. This provides a real-time, "typing" experience.
    *   **For Inactive Devices/Chats:** Other devices, or devices with a different chat open, do **not** receive the streaming updates for that conversation. Instead, they receive a single, lightweight `ai_message_ready` notification only after the assistant's response is fully complete and saved. This prevents background chats from causing unnecessary UI updates and network traffic.

3.  **Seamless Transitions:**
    *   If a user is watching an AI response stream on their laptop and then switches to a different chat on their phone, the streaming to the laptop for the first chat continues unaffected. The phone will now become the "active" device for the new chat and will receive streaming updates for it, if any occur.

## 4. Server-Side Caching Strategy

The server cache (Redis) is used to accelerate the sync process and reduce load on Directus.

*   **"Hot" Cache (Long TTL - e.g., 7 days):**
    *   **What:** The **full data (metadata + all messages)** for the **3 most recently edited chats** per user.
    *   **Purpose:** Provides instantaneous loading for a user's most active conversations. This is used in Phase 1 (High-Priority Load).

*   **"Warm" Cache (Short TTL - e.g., 5 minutes):**
    *   **What:** The **metadata only** (title, versions, timestamps) for the **100 most recently edited chats** per user.
    *   **Purpose:** Speeds up the main sync process (Phase 2). The server can perform the version comparison almost entirely from this cache.

## 5. Client-Side State Management

*   **Persistence:** IndexedDB is the client-side database.
    *   A `chats` table stores chat metadata and versions.
    *   A `messages` table stores message objects.
    *   A `sync_state` table stores the `last_sync_timestamp`.
*   **Reactivity:** Svelte stores are hydrated from IndexedDB and are updated when new data arrives from the WebSocket, driving UI updates.
*   **Bulk Operations:** All data processing from the server is handled with bulk database operations to prevent UI stuttering.
