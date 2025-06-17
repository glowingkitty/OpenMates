/**
 * @file websocketService.ts
 * @description Manages the WebSocket connection, message sending/receiving, and handler registration.
 * This service handles automatic reconnection, authentication-based connection management,
 * and routes incoming messages to registered handlers based on message type.
 * It also provides a mechanism for other parts of the application to listen to generic
 * WebSocket events like 'open', 'close', 'error', and 'message'.
 */
import { getWebSocketUrl } from '../config/api';
import { authStore } from '../stores/authStore'; // To check login status
import { get } from 'svelte/store'; // Import get
import { websocketStatus, type WebSocketStatus } from '../stores/websocketStatusStore'; // Import the new shared store
import { notificationStore } from '../stores/notificationStore'; // Import notification store

// Define message types based on the plan (can be expanded)
// Add known message types for better clarity if possible
type KnownMessageTypes =
    // === Client to Server ===
    | 'initial_sync_request'           // Section 5.2: Client sends its local state (chat_id + versions map)
    | 'update_title'                   // Section 6.2: Client sends new title
    | 'update_draft'                   // Section 7.2: Client sends new draft (Tiptap JSON or null)
    | 'delete_chat'                    // Client requests to delete a chat
    | 'sync_offline_changes'           // Section 10.3: Client sends queued offline changes
    | 'request_chat_content_batch'     // Section 5.5: Client requests full message history for new/updated chats if not sent initially
    | 'ping'                           // Standard keep-alive

    // === Server to Client ===
    | 'initial_sync_response'          // Section 5.4 & initial_sync_handler.py: Server responds with sync plan, deltas, and full chat order
    | 'priority_chat_ready'            // Section 4.2, Phase 1: Server notification that target chat (from last_opened_path) is ready in cache
    | 'cache_primed'                   // Section 4.2, Phase 2: Server notification that general cache warming (e.g., 1000 chats list_item_data & versions) is ready
    | 'chat_title_updated'             // Section 6.3 & title_update_handler.py: Broadcast of title change (includes new title_v)
    | 'chat_draft_updated'             // Section 7.3 & draft_update_handler.py: Broadcast of draft change (includes new draft_v and last_edited_overall_timestamp)
    | 'chat_message_added'          // Section 8 & (implicitly by message persistence logic): Broadcast of a new message (includes new message object, messages_v, last_edited_overall_timestamp)
    | 'chat_deleted'                   // delete_chat_handler.py: Broadcast that a chat was deleted (client should remove from local store)
    | 'offline_sync_complete'          // offline_sync_handler.py: Response to sync_offline_changes, indicating status of processed offline items
    | 'error'                          // General error message from server (e.g., validation failure, unexpected issue)
    | 'pong'                           // Response to client's ping

    // Specific error/conflict types (if still used by backend, though new architecture aims to minimize client-side conflict states)
    | 'draft_conflict'                 // Potentially for server-side rejection of a draft update if absolutely necessary (e.g. version mismatch not caught by offline logic)

    // UI/Internal Events (dispatched locally by WebSocketService, not actual WS message types from server)
    | 'reAuthRequired'                 // E.g., if server closes connection with a code indicating 2FA needed
    | 'authError'                      // E.g., if server closes connection with a generic auth policy violation
    | 'connection_failed_reconnect'    // UI notification: Max reconnect attempts reached
    | 'connection_failed_initial'      // UI notification: Initial connection attempt failed

    // Kept for potential future use (e.g., LLM message streaming)
    | 'message_update'                 // For streaming updates to a message content while it's being generated
    | 'user_credits_updated'

    ;

interface WebSocketMessage {
    type: KnownMessageTypes | string; // Allow known types + any string
    payload: any;
}

type MessageHandler = (payload: any) => void;

class WebSocketService extends EventTarget {
    private ws: WebSocket | null = null;
    private url: string | null = null;
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 10;
    private reconnectInterval = 1000; // Start with 1 second
    private maxReconnectInterval = 30000; // Max 30 seconds
    private messageHandlers: Map<string, MessageHandler[]> = new Map();
    private connectionPromise: Promise<void> | null = null;
    private resolveConnectionPromise: (() => void) | null = null;
    private rejectConnectionPromise: ((reason?: any) => void) | null = null;
    private pingIntervalId: NodeJS.Timeout | null = null;
    private readonly PING_INTERVAL = 25000; // 25 seconds, less than typical 30-60s timeouts
    private pongTimeoutId: NodeJS.Timeout | null = null; // Track pong timeout
    private readonly PONG_TIMEOUT = 5000; // 5 seconds to wait for pong

    // Add a set of message types that are allowed to have no handler (e.g., ack/info types)
    private readonly allowedNoHandlerTypes = new Set<string>([
        'active_chat_set_ack',
        // Add more types here if needed
    ]);

    constructor() {
        super();
        // Listen to auth changes to connect/disconnect
        authStore.subscribe(auth => {
            if (auth.isAuthenticated) {
                // Only attempt to connect if not already connected AND no connection attempt is in progress.
                if (!this.isConnected() && !this.connectionPromise) {
                    console.debug('[WebSocketService] Auth detected, no active connection or pending attempt, connecting...');
                    this.connect().catch(err => {
                        // Catch errors from connect() here if it's called without await
                        // and we don't want them to be unhandled.
                        console.warn('[WebSocketService] Connection attempt triggered by authStore failed:', err);
                    });
                } else if (this.isConnected()) {
                    console.debug('[WebSocketService] Auth detected, already connected.');
                } else if (this.connectionPromise) {
                    console.debug('[WebSocketService] Auth detected, connection attempt already in progress.');
                }
            } else if (!auth.isAuthenticated && (this.isConnected() || this.connectionPromise)) {
                // If no longer authenticated, and EITHER connected OR an attempt is in progress, then disconnect.
                console.debug('[WebSocketService] No longer authenticated, disconnecting active/pending connection...');
                this.disconnect(); // disconnect() handles nulling out ws and connectionPromise
                websocketStatus.setStatus('disconnected');
            }
        });
        this.registerDefaultErrorHandlers();
        this.registerPongHandler(); // Add call to new pong handler registration
    }

    private registerDefaultErrorHandlers(): void {
        this.on('error', (payload: any) => {
            console.error('[WebSocketService] Received error message from server:', payload);
            let errorMessage = 'An unexpected error occurred on the server.';
            if (payload && typeof payload.message === 'string') {
                errorMessage = payload.message;
            } else if (typeof payload === 'string') {
                errorMessage = payload;
            }
            notificationStore.error(`Server error: ${errorMessage}`);
        });
    }

    private registerPongHandler(): void {
        this.on('pong', (payload: any) => {
            // Pong received, clear pong timeout
            if (this.pongTimeoutId) {
                clearTimeout(this.pongTimeoutId);
                this.pongTimeoutId = null;
            }
            // No log unless error
        });
    }

    public connect(): Promise<void> {
         // If already connected or connecting, return existing promise
        if (this.isConnected() || this.connectionPromise) {
            return this.connectionPromise || Promise.resolve();
        }

        if (!get(authStore).isAuthenticated) {
            console.warn('[WebSocketService] Cannot connect: User not authenticated.');
            websocketStatus.setStatus('disconnected'); // Ensure status is disconnected
            return Promise.reject('User not authenticated');
        }

        // --- START ADDITION: Update Status ---
        const isReconnecting = this.reconnectAttempts > 0;
        websocketStatus.setStatus(isReconnecting ? 'reconnecting' : 'connecting');

        this.url = getWebSocketUrl();
        console.debug(`[WebSocketService] Attempting to connect to ${this.url}${isReconnecting ? ` (Reconnect attempt ${this.reconnectAttempts})` : ''}`);

        // Create a new promise for this connection attempt
        this.connectionPromise = new Promise((resolve, reject) => {
            this.resolveConnectionPromise = resolve;
            this.rejectConnectionPromise = reject;

            try {
                const currentWS = new WebSocket(this.url); // Create new instance
                this.ws = currentWS; // Make this the current WS instance for the service

                currentWS.onopen = () => {
                    if (this.ws !== currentWS) { // Check if this instance is still the "active" one
                        console.warn('[WebSocketService] onopen from a superseded WebSocket instance. Closing it and ignoring event.');
                        currentWS.close(1000, 'Superseded by new connection attempt');
                        return;
                    }
                    console.info('[WebSocketService] Connection established.');
                    this.reconnectAttempts = 0; // Reset on successful connection
                    this.reconnectInterval = 1000; // Reset interval
                    this.dispatchEvent(new CustomEvent('open'));
                    websocketStatus.setStatus('connected'); // Update status
                    this.startPing(); // Start pinging on successful connection
                    if (this.resolveConnectionPromise) {
                        this.resolveConnectionPromise();
                    }
                    this.connectionPromise = null; // Clear promise on success
                };

                currentWS.onmessage = (event) => {
                    if (this.ws !== currentWS && this.isConnected()) {
                        if (process.env.NODE_ENV !== 'production') {
                            console.warn('[WebSocketService] onmessage from a superseded WebSocket instance while a newer connection is active. Ignoring message.');
                        }
                        return;
                    }
                    try {
                        const rawMessage = JSON.parse(event.data as string);
                        // Only log if not ping/pong
                        if (rawMessage.type !== 'ping' && rawMessage.type !== 'pong') {
                            console.debug('[WebSocketService] Raw received data:', rawMessage);
                        }

                        let messageType: string | undefined;
                        let messagePayload: any;
                        let dispatchEventDetail: { type: string; payload: any };

                        if (typeof rawMessage.type === 'string') {
                            messageType = rawMessage.type;
                            messagePayload = rawMessage.payload;
                            dispatchEventDetail = rawMessage as WebSocketMessage;
                        } else if (typeof rawMessage.event === 'string') {
                            messageType = rawMessage.event;
                            messagePayload = rawMessage;
                            dispatchEventDetail = { type: messageType, payload: rawMessage };
                        } else {
                            console.warn('[WebSocketService] Received message with unknown structure (no type or event field):', rawMessage);
                            this.dispatchEvent(new CustomEvent('message_error', { detail: { error: 'Unknown message structure', data: rawMessage } }));
                            return;
                        }

                        if (messageType !== 'ping' && messageType !== 'pong') {
                            console.debug(`[WebSocketService] Determined messageType: "${messageType}"`);
                        }
                        this.dispatchEvent(new CustomEvent('message', { detail: dispatchEventDetail }));

                        // Call specific handlers
                        if (messageType) {
                            const handlers = this.messageHandlers.get(messageType);
                            if (handlers && handlers.length > 0) {
                                if (messageType !== 'ping' && messageType !== 'pong') {
                                    console.debug(`[WebSocketService] Found ${handlers.length} handler(s) for type "${messageType}". Executing...`);
                                }
                                handlers.forEach((handler, index) => {
                                    try {
                                        if (messageType !== 'ping' && messageType !== 'pong') {
                                            console.debug(`[WebSocketService] Executing handler #${index + 1} for type "${messageType}"`);
                                        }
                                        handler(messagePayload); // Pass the correctly determined payload
                                    } catch (handlerError) {
                                        console.error(`[WebSocketService] Error in message handler #${index + 1} for type "${messageType}":`, handlerError);
                                    }
                                });
                            } else if (!this.allowedNoHandlerTypes.has(messageType)) {
                                if (messageType !== 'ping' && messageType !== 'pong') {
                                    console.warn(`[WebSocketService] No handlers found for message.type: "${messageType}". Registered handlers:`, this.messageHandlers);
                                }
                            }
                        }
                    } catch (error) {
                        console.error('[WebSocketService] Error parsing message or in handler:', error, 'Raw Data:', event.data);
                        this.dispatchEvent(new CustomEvent('message_error', { detail: { error: 'Parsing/handling error', originalError: error, data: event.data } }));
                    }
                };

                currentWS.onerror = (event) => {
                    // ADDED: Detailed log for onerror
                    console.error(`[WebSocketService] DEBUG: onerror triggered. Event:`, event, `For WS URL: ${currentWS.url}, Current this.ws URL: ${this.ws?.url}`);

                    // If this error is for an old WebSocket instance, and not the current this.ws, log and ignore for main promise.
                    if (this.ws !== null && this.ws !== currentWS) {
                        console.warn('[WebSocketService] onerror from a superseded WebSocket instance:', event);
                        return;
                    }
                    console.error('[WebSocketService] WebSocket error:', event); // Keep original error log
                    this.dispatchEvent(new CustomEvent('error', { detail: event }));

                    // Only reject the main connectionPromise if this error is from the current WebSocket attempt
                    if (this.rejectConnectionPromise && this.ws === currentWS) {
                        this.rejectConnectionPromise('WebSocket error');
                        this.connectionPromise = null; // Clear promise on error for the current attempt
                    }
                    // Don't set status to failed here, let onclose handle it if it's also called.
                    // However, an error often precedes a close.
                };
    
                currentWS.onclose = (event) => {
                    // ADDED: Initial log to confirm onclose is triggered and see event details
                    console.log(`[WebSocketService] DEBUG: onclose triggered. Code: ${event.code}, Reason: '${event.reason}', Clean: ${event.wasClean}, For WS URL: ${currentWS.url}, Current this.ws URL: ${this.ws?.url}`);

                    // If this.ws is not null AND this.ws is not the currentWS that's closing,
                    // it means this is a close event from an older, superseded WebSocket instance.
                    // We should ignore it for the main state management (reconnect logic, main promise).
                    if (this.ws !== null && this.ws !== currentWS) {
                        // ADDED: More specific log when ignoring superseded instance
                        console.warn(`[WebSocketService] DEBUG: onclose event from a superseded WebSocket instance (event for ${currentWS.url}, code ${event.code}) is being IGNORED because current this.ws is ${this.ws?.url}.`);
                        return;
                    }

                    // If we reach here, this onclose event is for the WebSocket instance that was (or still is) this.ws,
                    // or this.ws was already null (meaning the last attempt failed and nulled it).
                    console.warn(`[WebSocketService] Connection closed. Code: ${event.code}, Reason: ${event.reason}, Clean: ${event.wasClean}`);
                    const currentStoreState = get(websocketStatus);
                    const previousStatus = currentStoreState.status;

                    // Important: Null out this.ws only if currentWS is indeed the one that was active and is now closing.
                    if (this.ws === currentWS) {
                        this.ws = null;
                        this.stopPing(); // Stop pinging if the active connection closes
                    }
                    
                    // Only dispatch 'close' if it wasn't already disconnected or in an error state
                    // and if this close event pertains to what was the active connection.
                    if (previousStatus !== 'disconnected' && previousStatus !== 'error') {
                        this.dispatchEvent(new CustomEvent('close', { detail: event }));
                    }
    
                    // Handle specific close codes
                    if (event.code === status.WS_1008_POLICY_VIOLATION) {
                        console.error('[WebSocketService] Connection closed due to policy violation (Auth Error/Device Mismatch). Won\'t reconnect automatically.');
                        websocketStatus.setError(event.reason || 'Connection closed due to policy violation.', 'error');
                        if (event.reason?.includes("2FA required")) {
                            this.dispatchEvent(new CustomEvent('reAuthRequired', { detail: { type: '2fa' } }));
                        } else {
                            this.dispatchEvent(new CustomEvent('authError'));
                        }
                        // Reject and clear the main connection promise only if this close event corresponds to the current attempt's promise
                        if (this.rejectConnectionPromise && (this.connectionPromise && !this.ws)) { // Check if a promise exists and no ws is active
                             this.rejectConnectionPromise(`Connection closed: ${event.reason}`);
                             this.connectionPromise = null;
                        }
                        return; // Do not attempt reconnect on auth errors
                    }

                    // Attempt to reconnect if not a deliberate disconnect or auth error
                    // This logic should only run if the closing WS was the "main" one or if no "main" one exists (this.ws is null)
                    if (get(authStore).isAuthenticated && this.reconnectAttempts < this.maxReconnectAttempts) {
                        websocketStatus.setStatus('reconnecting');
                        this.reconnectAttempts++;
                        const delay = Math.min(this.reconnectInterval * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectInterval);
                        console.info(`[WebSocketService] Attempting reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms...`);
                        
                        // Clear the current connection promise before scheduling a new connect,
                        // if this onclose pertains to the promise of the current attempt.
                        if (this.rejectConnectionPromise && (this.connectionPromise && !this.ws)) {
                            // Don't reject, as a reconnect is pending. Just clear.
                            // Or, the promise is for a single attempt, so it should be rejected.
                            // Let's assume promise is for single attempt for now.
                            this.rejectConnectionPromise(new Error(`Connection closed (code ${event.code}), attempting reconnect.`));
                            this.connectionPromise = null;
                        } else if (this.connectionPromise && !this.ws) {
                            // If rejectConnectionPromise is null but promise exists (e.g. resolved by a racing onopen)
                            this.connectionPromise = null;
                        }

                        setTimeout(() => this.connect(), delay);
                    } else if (get(authStore).isAuthenticated) { // Max reconnect attempts reached
                        console.error('[WebSocketService] Max reconnect attempts reached. Giving up.');
                        websocketStatus.setError('Max reconnect attempts reached. Giving up.', 'error');
                        this.dispatchEvent(new CustomEvent('connection_failed_reconnect'));
                        if (this.rejectConnectionPromise && (this.connectionPromise && !this.ws)) {
                             this.rejectConnectionPromise('Max reconnect attempts reached');
                             this.connectionPromise = null;
                        }
                    } else { // User logged out
                        websocketStatus.setStatus('disconnected');
                        if (this.rejectConnectionPromise && (this.connectionPromise && !this.ws)) {
                            this.rejectConnectionPromise('User logged out during connection attempt.');
                        }
                        this.connectionPromise = null; // Clear promise
                    }
                };
            } catch (error) {
                console.error('[WebSocketService] Failed to create WebSocket:', error);
                const errorMessage = error instanceof Error ? error.message : String(error);
                websocketStatus.setError(errorMessage, 'error');
                // Dispatch specific event for UI feedback
                // UI should listen for 'connection_failed_initial' and inform the user about the initial connection failure
                this.dispatchEvent(new CustomEvent('connection_failed_initial', { detail: error }));
                 if (this.rejectConnectionPromise) {
                      this.rejectConnectionPromise(error);
                 }
                 this.connectionPromise = null; // Clear promise on creation failure
            }
        });

        return this.connectionPromise;
    }

    public disconnect(): void {
        if (this.ws) {
            console.info('[WebSocketService] Disconnecting...');
            this.reconnectAttempts = this.maxReconnectAttempts; // Prevent reconnect attempts on manual disconnect
                        this.ws.close(1000, 'Client initiated disconnect'); // Normal closure
            this.ws = null;
        }
        this.stopPing(); // Stop pinging on disconnect
        // Ensure status is set even if already disconnected
        websocketStatus.setStatus('disconnected');
         if (this.rejectConnectionPromise) {
             this.rejectConnectionPromise('Manual disconnect'); // Reject any pending connection promise
         }
        this.connectionPromise = null; // Clear connection promise
    }

    private startPing(): void {
        this.stopPing(); // Clear any existing ping interval
        this.pingIntervalId = setInterval(() => {
            if (this.isConnected()) {
                try {
                    this.sendMessage('ping', {}); // sendMessage already checks for connection
                    // Start pong timeout
                    if (this.pongTimeoutId) {
                        clearTimeout(this.pongTimeoutId);
                    }
                    this.pongTimeoutId = setTimeout(() => {
                        console.error('[WebSocketService] Pong not received within timeout after ping. Connection is likely stale. Attempting to close and trigger reconnect.');
                        if (this.ws) {
                            // Attempt to close the WebSocket. This should trigger the onclose handler,
                            // which contains the reconnection logic.
                            console.log('[WebSocketService] Pong Timeout: Closing current WebSocket with code 1000 to trigger reconnect sequence.');
                            this.ws.close(1000, "Pong timeout - client initiated close"); // Use code 1000
                            // No need to call this.ws = null or this.stopPing() here, as onclose should handle it.
                        } else {
                            // If ws is already null (e.g., due to a race condition or prior error),
                            // directly attempt a reconnect if authenticated.
                            console.warn('[WebSocketService] Pong Timeout: this.ws is already null. Directly attempting reconnect if authenticated.');
                            if (get(authStore).isAuthenticated && this.reconnectAttempts < this.maxReconnectAttempts) {
                                // Manually trigger parts of the onclose logic for reconnection
                                websocketStatus.setStatus('reconnecting');
                                this.reconnectAttempts++;
                                const delay = Math.min(this.reconnectInterval * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectInterval);
                                console.info(`[WebSocketService] Pong Timeout: Attempting direct reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms...`);
                                setTimeout(() => this.connect(), delay);
                            } else if (get(authStore).isAuthenticated) {
                                console.error('[WebSocketService] Pong Timeout: Max reconnect attempts reached during direct attempt. Giving up.');
                                websocketStatus.setError('Max reconnect attempts reached after pong timeout.', 'error');
                                this.dispatchEvent(new CustomEvent('connection_failed_reconnect'));
                            }
                        }
                    }, this.PONG_TIMEOUT);
                } catch (error) {
                    console.warn('[WebSocketService] Error sending ping:', error);
                    // If ping fails, connection might be stale. Reconnect logic in onclose should handle it.
                }
            }
        }, this.PING_INTERVAL);
    }

    private stopPing(): void {
        if (this.pingIntervalId) {
            clearInterval(this.pingIntervalId);
            this.pingIntervalId = null;
        }
        if (this.pongTimeoutId) {
            clearTimeout(this.pongTimeoutId);
            this.pongTimeoutId = null;
        }
    }

    public isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
    }

    public async sendMessage(type: string, payload: any): Promise<void> {
        const message: WebSocketMessage = { type, payload };
        if (!this.isConnected()) {
            if (type !== 'ping') {
                console.warn('[WebSocketService] Not connected. Attempting to connect before sending.');
            }
            try {
                await this.connect(); // Wait for connection
            } catch (error) {
                if (type !== 'ping') {
                    console.error('[WebSocketService] Connection failed, cannot send message:', message);
                }
                throw new Error('WebSocket not connected');
            }
        }

        // Check again after attempting connection
        if (this.isConnected()) {
            try {
                if (type !== 'ping') {
                    console.debug('[WebSocketService] Sending message:', message);
                }
                this.ws?.send(JSON.stringify(message));
            } catch (error) {
                if (type !== 'ping') {
                    console.error('[WebSocketService] Error sending message:', error);
                }
                throw error; // Re-throw error after logging
            }
        } else {
            if (type !== 'ping') {
                console.error('[WebSocketService] Still not connected after attempt, cannot send message:', message);
            }
            throw new Error('WebSocket not connected after reconnect attempt');
        }
    }

    // Register handlers for specific message types
    public on(messageType: string, handler: MessageHandler): void {
        if (!this.messageHandlers.has(messageType)) {
            this.messageHandlers.set(messageType, []);
        }
        const currentHandlers = this.messageHandlers.get(messageType);
        currentHandlers?.push(handler);
        // console.log(`[WebSocketService] Registered handler for messageType: "${messageType}". Total handlers for this type: ${currentHandlers?.length}. Handler function:`, handler.name || 'anonymous');
        // if (messageType === 'chat_draft_updated') {
        //     console.log(`[WebSocketService] Specifically, a handler for 'chat_draft_updated' was just registered.`);
        // }
    }

    // Unregister handlers
    public off(messageType: string, handler: MessageHandler): void {
        const handlers = this.messageHandlers.get(messageType);
        if (handlers) {
            const index = handlers.indexOf(handler);
            if (index > -1) {
                handlers.splice(index, 1);
            }
            if (handlers.length === 0) {
                this.messageHandlers.delete(messageType);
            }
        }
    }
}

// Export a singleton instance
export const webSocketService = new WebSocketService();

// Add status constants from FastAPI if not already available globally
// These might need adjustment based on actual FastAPI status codes used
const status = {
    WS_1000_NORMAL_CLOSURE: 1000,
    WS_1001_GOING_AWAY: 1001,
    WS_1002_PROTOCOL_ERROR: 1002,
    WS_1003_UNSUPPORTED_DATA: 1003,
    WS_1005_NO_STATUS_RCVD: 1005,
    WS_1006_ABNORMAL_CLOSURE: 1006,
    WS_1007_INVALID_FRAMEWORK_PAYLOAD_DATA: 1007,
    WS_1008_POLICY_VIOLATION: 1008,
    WS_1009_MESSAGE_TOO_BIG: 1009,
    WS_1010_MANDATORY_EXT: 1010,
    WS_1011_INTERNAL_ERROR: 1011,
    WS_1012_SERVICE_RESTART: 1012,
    WS_1013_TRY_AGAIN_LATER: 1013,
    WS_1014_BAD_GATEWAY: 1014,
    WS_1015_TLS_HANDSHAKE: 1015,
};
