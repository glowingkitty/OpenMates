import type { ChatSynchronizationService } from './chatSyncService';
import { webSocketService } from './websocketService';
import type { StoreEmbedPayload } from '../types/chat';

/**
 * Send encrypted embed to server for Directus storage
 */
export async function sendStoreEmbedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: StoreEmbedPayload
): Promise<void> {
    // Check connection status safely
    const isConnected = (serviceInstance as any).webSocketConnected || 
                        (serviceInstance as any).webSocketConnected_FOR_SENDERS_ONLY;
                        
    if (!isConnected) {
        console.warn('[EmbedSenders] Cannot send store_embed - WebSocket not connected');
        // TODO: Queue for offline sync?
        return;
    }

    try {
        console.debug(`[EmbedSenders] Sending encrypted embed ${payload.embed_id} to server`);
        await webSocketService.sendMessage('store_embed', payload);
    } catch (error) {
        console.error('[EmbedSenders] Error sending store_embed:', error);
        throw error;
    }
}