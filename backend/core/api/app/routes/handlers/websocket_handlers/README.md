# WebSocket Message Handlers

This directory contains individual Python modules responsible for handling specific types of messages received over the WebSocket connection. Each handler encapsulates the logic for processing a particular client action or server event.

## Purpose

The primary goal of organizing handlers into separate files is to:
-   **Improve Modularity:** Keep the main `websockets.py` file cleaner and focused on connection management and message routing.
-   **Enhance Readability:** Make it easier to understand the logic for each specific WebSocket action.
-   **Simplify Maintenance:** Allow developers to modify or debug individual handlers without navigating a monolithic file.
-   **Promote Testability:** Facilitate unit testing of individual handler functions.

## Handler Function Signature

Most handler functions are expected to follow a similar asynchronous signature:

```python
async def handle_specific_action(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: ConnectionManager, # The WebSocket connection manager
    user_id: str,               # Authenticated user ID
    device_fingerprint_hash: str, # Specific device identifier for the connection
    payload: Dict[str, Any],    # The payload of the WebSocket message
    websocket: WebSocket (optional) # The raw WebSocket connection, if direct interaction is needed beyond manager
) -> None:
    # Handler logic here
    # Use manager.send_personal_message() or manager.broadcast_to_user_specific_event() to send responses/events
```

## Current Handlers:

-   `initial_sync_handler.py`: Handles the `initial_sync_request` from the client to synchronize its local state with the server.
-   `title_update_handler.py`: Processes requests to update a chat's title.
-   `draft_update_handler.py`: Manages updates to a user's draft for a specific chat.
-   `delete_draft_handler.py`: Handles requests to delete a user's draft for a chat.
-   `message_received_handler.py`: Processes new messages sent by a client to a chat.
-   `delete_chat_handler.py`: Handles requests to delete an entire chat.
-   `offline_sync_handler.py`: Manages the synchronization of changes made by the client while offline.
-   `get_chat_messages_handler.py`: Handles requests to fetch messages for a single, specific chat (often used when a user opens a chat not in the immediate cache).
-   `chat_content_batch_handler.py`: Processes requests from the client to fetch message content for a batch of specified chats, typically after an initial sync.

## Adding New Handlers

1.  Create a new Python file in this directory (e.g., `new_action_handler.py`).
2.  Define an `async` handler function within the file, following the typical signature.
3.  Implement the logic for the new action.
4.  Import the handler function into `backend/core/api/app/routes/websockets.py`.
5.  Add a new `elif` block in the main message loop within `websockets.py` to route messages of the new type to your handler.