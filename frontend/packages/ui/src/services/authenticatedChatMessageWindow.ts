/** Canonical encrypted message windows shared by chat display and voice context. */
import { get } from 'svelte/store';
import type { Chat, ChatCompressionCheckpoint, Message as ChatMessageModel } from '../types/chat';
import { chatDB } from './db';
import { getApiEndpoint, storageArchiveFetch } from '../config/api';
import { activeTeamId } from '../stores/teamStore';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';

function isChatInActiveTeamContext(chat: Chat, teamId: string | null): boolean {
  return teamId ? chat.team_id === teamId : !chat.team_id;
}

type AuthenticatedMessageWindowPayload = {
    messages?: Array<string | Record<string, unknown>>;
    has_more_before?: boolean;
    has_more_after?: boolean;
    start_cursor?: { created_at?: number; message_id?: string } | null;
    end_cursor?: { created_at?: number; message_id?: string } | null;
    anchor_found?: boolean;
    oversized_message_cursor?: { created_at: number; message_id: string } | null;
};

export function normalizeServerMessage(raw: string | Record<string, unknown>, chatId: string): ChatMessageModel | null {
    const messageObj = typeof raw === 'string' ? JSON.parse(raw) as Record<string, unknown> : raw;
    if (messageObj.chat_id && messageObj.chat_id !== chatId) return null;
    const messageId = messageObj.client_message_id || messageObj.message_id || messageObj.id;
    if (typeof messageId !== 'string') return null;
    return {
        message_id: messageId,
        chat_id: typeof messageObj.chat_id === 'string' ? messageObj.chat_id : chatId,
        role: messageObj.role === 'assistant' || messageObj.role === 'system' ? messageObj.role : 'user',
        created_at: typeof messageObj.created_at === 'number' ? messageObj.created_at : Math.floor(Date.now() / 1000),
        status: 'synced',
        // Zero is the server's recoverable created-but-not-counted call marker.
        queue_revision: typeof messageObj.queue_revision === 'number' &&
            Number.isSafeInteger(messageObj.queue_revision) && messageObj.queue_revision >= 0
            ? messageObj.queue_revision : undefined,
        encrypted_content: typeof messageObj.encrypted_content === 'string' ? messageObj.encrypted_content : '',
        encrypted_sender_name: typeof messageObj.encrypted_sender_name === 'string' ? messageObj.encrypted_sender_name : undefined,
        hashed_user_id: typeof messageObj.hashed_user_id === 'string' ? messageObj.hashed_user_id : undefined,
        encrypted_category: typeof messageObj.encrypted_category === 'string' ? messageObj.encrypted_category : undefined,
        encrypted_model_name: typeof messageObj.encrypted_model_name === 'string' ? messageObj.encrypted_model_name : undefined,
        encrypted_thinking_content: typeof messageObj.encrypted_thinking_content === 'string' ? messageObj.encrypted_thinking_content : undefined,
        encrypted_thinking_signature: typeof messageObj.encrypted_thinking_signature === 'string' ? messageObj.encrypted_thinking_signature : undefined,
        has_thinking: typeof messageObj.has_thinking === 'boolean' ? messageObj.has_thinking : undefined,
        thinking_token_count: typeof messageObj.thinking_token_count === 'number' ? messageObj.thinking_token_count : undefined,
        user_message_id: typeof messageObj.user_message_id === 'string' ? messageObj.user_message_id : undefined,
        encrypted_pii_mappings: typeof messageObj.encrypted_pii_mappings === 'string' ? messageObj.encrypted_pii_mappings : undefined,
        client_message_id: typeof messageObj.client_message_id === 'string' ? messageObj.client_message_id : undefined,
        key_version: typeof messageObj.key_version === 'number' ? messageObj.key_version : undefined,
    };
}

export async function fetchAuthenticatedChatMessageWindow(chatId: string, options: {
    direction: 'latest' | 'before' | 'after' | 'around';
    limit?: number;
    includeCanonicalMessages?: boolean;
    beforeTimestamp?: number;
    beforeMessageId?: string;
    anchorMessageId?: string;
    compressedUpToTimestamp?: number;
    respectCompressionBoundary?: boolean;
}, fallbackChat?: Chat | null) {
    const teamScope = get(activeTeamId);
    const scopeEpoch = getWorkspaceCacheEpoch();
    const storedChat = await chatDB.getRawChat(chatId);
    const scopedChat = storedChat ?? (fallbackChat?.chat_id === chatId ? fallbackChat : null);
    if (scopeEpoch !== getWorkspaceCacheEpoch() || get(activeTeamId) !== teamScope
        || (scopedChat && !isChatInActiveTeamContext(scopedChat, teamScope))
        || (teamScope && !scopedChat)) {
        throw new Error('Chat message window is outside the active workspace');
    }
    const params = new URLSearchParams({
        direction: options.direction,
        limit: String(options.limit ?? 30),
    });
    if (scopedChat?.team_id) params.set('team_id', scopedChat.team_id);
    if (typeof options.beforeTimestamp === 'number') params.set('before_timestamp', String(options.beforeTimestamp));
    if (options.beforeMessageId) params.set('before_message_id', options.beforeMessageId);
    if (options.anchorMessageId) params.set('anchor_message_id', options.anchorMessageId);
    if (options.respectCompressionBoundary === false) params.set('respect_compression_boundary', 'false');

    const response = await storageArchiveFetch(getApiEndpoint(`/v1/chats/${chatId}/messages/window?${params.toString()}`), {
        credentials: 'include',
    });
    if (!response.ok) throw new Error(`Authenticated message-window fetch failed: ${response.status}`);
    const payload = await response.json() as AuthenticatedMessageWindowPayload;
    if (scopeEpoch !== getWorkspaceCacheEpoch() || get(activeTeamId) !== teamScope) {
        throw new Error('Chat message window arrived after workspace switch');
    }
    const parsedMessages = (payload.messages || []).flatMap((raw) => {
        const normalized = normalizeServerMessage(raw, chatId);
        return normalized ? [normalized] : [];
    });
    if (payload.oversized_message_cursor) {
        const selectedId = payload.oversized_message_cursor.message_id;
        const exactParams = new URLSearchParams();
        if (scopedChat?.team_id) exactParams.set('team_id', scopedChat.team_id);
        const exactPath = `/v1/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(selectedId)}`;
        const exactResponse = await storageArchiveFetch(getApiEndpoint(`${exactPath}${exactParams.size ? `?${exactParams}` : ''}`), {
            credentials: 'include',
        });
        if (!exactResponse.ok) throw new Error(`Selected message fetch failed: ${exactResponse.status}`);
        const exactPayload = await exactResponse.json() as { message?: Record<string, unknown> };
        const selected = exactPayload.message && normalizeServerMessage(exactPayload.message, chatId);
        if (!selected || selected.message_id !== selectedId) throw new Error('Selected message identity mismatch');
        parsedMessages.push(selected);
    }
    if (parsedMessages.length === 0 && payload.has_more_before) {
        throw new Error('Message window continuation returned no selected ciphertext');
    }
    if (scopeEpoch !== getWorkspaceCacheEpoch() || get(activeTeamId) !== teamScope) {
        throw new Error('Chat message window arrived after workspace switch');
    }
    if (parsedMessages.length > 0) {
        await chatDB.batchSaveMessages(parsedMessages);
    }
    // A local limited window can include newer pending rows and displace rows
    // selected by the server. Voice must use exactly the canonical page IDs
    // before advancing its matching server cursor.
    const canonicalMessages = options.includeCanonicalMessages
        ? await Promise.all(parsedMessages.map(message => chatDB.getMessage(message.message_id))) : undefined;
    if (canonicalMessages?.some(message => !message || message.chat_id !== chatId)) {
        throw new Error('Canonical call history could not be loaded');
    }
    const localWindow = await chatDB.getMessageWindowForChat(chatId, {
        direction: options.direction,
        limit: options.limit,
        beforeTimestamp: options.beforeTimestamp,
        beforeMessageId: options.beforeMessageId,
        anchorMessageId: options.anchorMessageId,
        compressedUpToTimestamp: options.compressedUpToTimestamp,
    });
    await chatDB.recordMessageWindowPage(chatId, localWindow, {
        direction: options.direction,
        pageKind: 'normal',
    });
    await chatDB.evictStaleMessageWindowPages(chatId, {
        protectedMessageIds: localWindow.messages.map((message) => message.message_id),
    });
    if (scopeEpoch !== getWorkspaceCacheEpoch() || get(activeTeamId) !== teamScope) {
        throw new Error('Chat message window completed after workspace switch');
    }
    return {
        ...localWindow,
        canonicalMessages: canonicalMessages as ChatMessageModel[] | undefined,
        startCursor: payload.start_cursor?.created_at ?? localWindow.startCursor,
        startCursorMessageId: payload.start_cursor?.message_id ?? localWindow.startCursorMessageId,
        hasMoreBefore: payload.has_more_before ?? localWindow.hasMoreBefore,
        hasMoreAfter: payload.has_more_after ?? localWindow.hasMoreAfter,
        anchorFound: payload.anchor_found ?? localWindow.anchorFound,
    };
}


/** Read the newest bounded checkpoint window before assembling a cold call. */
export async function loadCanonicalCallCheckpoints(chatId: string): Promise<ChatCompressionCheckpoint[]> {
    const epoch = getWorkspaceCacheEpoch();
    if (get(activeTeamId)) throw new Error('Voice calls require a personal workspace');
    const current = () => epoch === getWorkspaceCacheEpoch() && !get(activeTeamId);
    const response = await storageArchiveFetch(getApiEndpoint(`/v1/chats/${encodeURIComponent(chatId)}/compression-checkpoints?limit=20`), { credentials: 'include' });
    if (!response.ok || !current()) throw new Error('Call checkpoints unavailable');
    const payload = await response.json() as { checkpoints?: ChatCompressionCheckpoint[]; oversized_checkpoint_id?: string };
    const checkpoints = payload.checkpoints ?? [];
    if (payload.oversized_checkpoint_id) {
        const exact = await storageArchiveFetch(getApiEndpoint(`/v1/chats/${encodeURIComponent(chatId)}/compression-checkpoints/${encodeURIComponent(payload.oversized_checkpoint_id)}`), { credentials: 'include' });
        if (!exact.ok || !current()) throw new Error('Call checkpoint unavailable');
        const selected = (await exact.json() as { checkpoint?: ChatCompressionCheckpoint }).checkpoint;
        if (!selected || selected.id !== payload.oversized_checkpoint_id) throw new Error('Call checkpoint identity changed');
        checkpoints.push(selected);
    }
    if (!current() || checkpoints.some(checkpoint => checkpoint.chat_id !== chatId)) throw new Error('Call checkpoint scope changed');
    for (const checkpoint of checkpoints) await chatDB.saveChatCompressionCheckpoint(checkpoint);
    return checkpoints;
}
