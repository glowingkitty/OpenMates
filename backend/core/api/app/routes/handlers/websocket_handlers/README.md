# This directory contains handler modules for WebSocket messages.

## Overview

This directory houses individual Python modules, each dedicated to handling a specific type of message received over the WebSocket connection. The primary purpose is to keep the main WebSocket routing logic in [`backend/core/api/app/routes/websockets.py`](../websockets.py) clean and maintainable by delegating message-specific processing to these specialized handlers.

Each handler is responsible for:
- Validating the incoming message payload.
- Interacting with relevant services (e.g., `CacheService`, `DirectusService`, `EncryptionService`).
- Performing the business logic associated with the message type.
- Sending appropriate responses or broadcasts back to clients via the `ConnectionManager`.

## Structure of a Handler

A typical handler module (e.g., `example_handler.py`) defines an asynchronous function, such as `async def handle_example_message(...)`. This function generally accepts a consistent set of parameters:

- `websocket: WebSocket`: The FastAPI `WebSocket` instance for the client connection.
- `manager: ConnectionManager`: The `ConnectionManager` instance for managing connections and sending messages.
- `cache_service: CacheService`: Service for cache interactions.
- `directus_service: DirectusService`: Service for backend (Directus) interactions.
- `encryption_service: EncryptionService`: Service for data encryption/decryption.
- `user_id: str`: The authenticated user's ID.
- `device_fingerprint_hash: str`: Hash of the client's device fingerprint.
- `payload: Dict[str, Any]`: The data payload of the incoming WebSocket message.

## Adding a New Handler

1.  **Create Handler File**: Add a new Python file in this directory (e.g., `new_action_handler.py`).
2.  **Define Handler Function**: Implement an `async def handle_new_action(...)` function within this file, including the standard parameters.
3.  **Implement Logic**: Add the specific business logic for the new message type.
4.  **Integrate with Router**:
    *   Import the new handler function in [`backend/core/api/app/routes/websockets.py`](../websockets.py).
    *   Add an `elif` block in the `websocket_endpoint` function in [`websockets.py`](../websockets.py) to route messages of the new type to your handler.

## Error Management

Handlers should include robust error handling (e.g., `try...except` blocks), log errors comprehensively, and send clear error messages to the client when appropriate.