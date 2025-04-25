import { getWebSocketUrl } from '../config/api';
import { authStore } from '../stores/authStore'; // To check login status
import { get, writable } from 'svelte/store'; // Import writable

// --- START ADDITION: Connection Status Store ---
export type WebSocketStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'failed';
export const websocketStatus = writable<WebSocketStatus>('disconnected');
// --- END ADDITION ---

// Define message types based on the plan (can be expanded)
interface WebSocketMessage {
    type: string;
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

    constructor() {
        super();
        // Listen to auth changes to connect/disconnect
        authStore.subscribe(auth => {
            if (auth.isAuthenticated && !this.isConnected()) {
                console.debug('[WebSocketService] Auth detected, connecting...');
                this.connect();
            } else if (!auth.isAuthenticated && this.isConnected()) {
                console.debug('[WebSocketService] No longer authenticated, disconnecting...');
                this.disconnect();
                websocketStatus.set('disconnected'); // Update status on auth change
            }
        });
    }

    public connect(): Promise<void> {
         // If already connected or connecting, return existing promise
        if (this.isConnected() || this.connectionPromise) {
            return this.connectionPromise || Promise.resolve();
        }

        if (!get(authStore).isAuthenticated) {
            console.warn('[WebSocketService] Cannot connect: User not authenticated.');
            websocketStatus.set('disconnected'); // Ensure status is disconnected
            return Promise.reject('User not authenticated');
        }

        // --- START ADDITION: Update Status ---
        const isReconnecting = this.reconnectAttempts > 0;
        websocketStatus.set(isReconnecting ? 'reconnecting' : 'connecting');
        // --- END ADDITION ---

        this.url = getWebSocketUrl();
        console.debug(`[WebSocketService] Attempting to connect to ${this.url}${isReconnecting ? ` (Reconnect attempt ${this.reconnectAttempts})` : ''}`);

        // Create a new promise for this connection attempt
        this.connectionPromise = new Promise((resolve, reject) => {
            this.resolveConnectionPromise = resolve;
            this.rejectConnectionPromise = reject;

            try {
                this.ws = new WebSocket(this.url); // Cookies should be sent automatically

                this.ws.onopen = () => {
                    console.info('[WebSocketService] Connection established.');
                    this.reconnectAttempts = 0; // Reset on successful connection
                    this.reconnectInterval = 1000; // Reset interval
                    this.dispatchEvent(new CustomEvent('open'));
                    websocketStatus.set('connected'); // Update status
                    if (this.resolveConnectionPromise) {
                        this.resolveConnectionPromise();
                    }
                    this.connectionPromise = null; // Clear promise on success
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message: WebSocketMessage = JSON.parse(event.data);
                        console.debug('[WebSocketService] Received message:', message);
                        this.dispatchEvent(new CustomEvent('message', { detail: message }));

                        // Call specific handlers
                        const handlers = this.messageHandlers.get(message.type);
                        if (handlers) {
                            handlers.forEach(handler => {
                                try {
                                    handler(message.payload);
                                } catch (handlerError) {
                                    console.error(`[WebSocketService] Error in message handler for type ${message.type}:`, handlerError);
                                }
                            });
                        }

                    } catch (error) {
                        console.error('[WebSocketService] Error parsing message or in handler:', error, 'Data:', event.data);
                    }
                };

                this.ws.onerror = (event) => {
                    console.error('[WebSocketService] WebSocket error:', event);
                    this.dispatchEvent(new CustomEvent('error', { detail: event }));
                    // Error might be followed by onclose, rely on onclose for reconnect logic
                    if (this.rejectConnectionPromise) {
                         this.rejectConnectionPromise('WebSocket error');
                        }
                         this.connectionPromise = null; // Clear promise on error
                         // Don't set status to failed here, let onclose handle it
                    };
    
                    this.ws.onclose = (event) => {
                        console.warn(`[WebSocketService] Connection closed. Code: ${event.code}, Reason: ${event.reason}, Clean: ${event.wasClean}`);
                        const previousStatus = get(websocketStatus);
                        this.ws = null;
                        // Only dispatch 'close' if it wasn't already disconnected or failed
                        if (previousStatus !== 'disconnected' && previousStatus !== 'failed') {
                            this.dispatchEvent(new CustomEvent('close', { detail: event }));
                        }

                    // Handle specific close codes
                    if (event.code === status.WS_1008_POLICY_VIOLATION) {
                         console.error('[WebSocketService] Connection closed due to policy violation (Auth Error/Device Mismatch). Won\'t reconnect automatically.');
                         websocketStatus.set('failed'); // Set status to failed on auth error
                         // TODO: Potentially trigger re-auth flow based on reason?
                         if (event.reason?.includes("2FA required")) {
                              // Dispatch an event for UI to handle 2FA prompt
                              // UI should listen for 'reAuthRequired' and show appropriate modal/view
                              this.dispatchEvent(new CustomEvent('reAuthRequired', { detail: { type: '2fa' } }));
                         } else {
                              // Dispatch generic auth error
                              // UI should listen for 'authError' and inform the user (e.g., toast notification)
                               this.dispatchEvent(new CustomEvent('authError'));
                               // Consider logging out if session is truly invalid
                               // authStore.logout();
                         }
                         if (this.rejectConnectionPromise) {
                              this.rejectConnectionPromise(`Connection closed: ${event.reason}`);
                         }
                         this.connectionPromise = null; // Clear promise on auth failure
                         return; // Do not attempt reconnect on auth errors
                     }

                     // Attempt to reconnect if not a deliberate disconnect or auth error
                     if (get(authStore).isAuthenticated && this.reconnectAttempts < this.maxReconnectAttempts) {
                         websocketStatus.set('reconnecting'); // Update status
                        this.reconnectAttempts++;
                        const delay = Math.min(this.reconnectInterval * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectInterval);
                        console.info(`[WebSocketService] Attempting reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms...`);
                        setTimeout(() => this.connect(), delay);
                        // Keep the connectionPromise pending during reconnection attempts
                    } else if (get(authStore).isAuthenticated) {
                        console.error('[WebSocketService] Max reconnect attempts reached. Giving up.');
                        websocketStatus.set('failed'); // Set status to failed
                        // Dispatch specific event for UI feedback
                        // UI should listen for 'connection_failed_reconnect' and inform the user connection was lost permanently
                        this.dispatchEvent(new CustomEvent('connection_failed_reconnect'));
                         if (this.rejectConnectionPromise) {
                              this.rejectConnectionPromise('Max reconnect attempts reached');
                         }
                         this.connectionPromise = null; // Clear promise on final failure
                    } else {
                         // User logged out, don't reject the promise, just clear it
                         websocketStatus.set('disconnected'); // Ensure status is disconnected
                         this.connectionPromise = null;
                    }
                };
            } catch (error) {
                console.error('[WebSocketService] Failed to create WebSocket:', error);
                websocketStatus.set('failed'); // Set status to failed
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
        // Ensure status is set even if already disconnected
        websocketStatus.set('disconnected');
         if (this.rejectConnectionPromise) {
             this.rejectConnectionPromise('Manual disconnect'); // Reject any pending connection promise
         }
        this.connectionPromise = null; // Clear connection promise
    }

    public isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
    }

    public async sendMessage(type: string, payload: any): Promise<void> {
        const message: WebSocketMessage = { type, payload };
        if (!this.isConnected()) {
            console.warn('[WebSocketService] Not connected. Attempting to connect before sending.');
            try {
                await this.connect(); // Wait for connection
            } catch (error) {
                 console.error('[WebSocketService] Connection failed, cannot send message:', message);
                 throw new Error('WebSocket not connected');
            }
        }

        // Check again after attempting connection
        if (this.isConnected()) {
            try {
                console.debug('[WebSocketService] Sending message:', message);
                this.ws?.send(JSON.stringify(message));
            } catch (error) {
                console.error('[WebSocketService] Error sending message:', error);
                throw error; // Re-throw error after logging
            }
        } else {
             console.error('[WebSocketService] Still not connected after attempt, cannot send message:', message);
             throw new Error('WebSocket not connected after reconnect attempt');
        }
    }

    // Register handlers for specific message types
    public on(messageType: string, handler: MessageHandler): void {
        if (!this.messageHandlers.has(messageType)) {
            this.messageHandlers.set(messageType, []);
        }
        this.messageHandlers.get(messageType)?.push(handler);
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