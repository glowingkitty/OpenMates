/**
 * Saves an opened daily inspiration as a real chat (TASK-3406, plan
 * daily-inspiration-deferred-chat).
 *
 * Opening an inspiration only shows an in-memory preview (see
 * pendingInspirationChat.ts). This runs when the user sends the first follow-up:
 * it creates the chat key, stores the encrypted chat and its first assistant
 * message, attaches the pre-stored inspiration video embed to the chat, marks the
 * inspiration opened, adds the chat to the list and syncs it to the server. The
 * steps and payloads are the ones ActiveChat used to run on open, unchanged.
 */
import type { Chat, Message } from '../types/chat';
import type { DailyInspiration } from '../stores/dailyInspirationStore';
import type { InspirationEmbedData } from './sendersSync';
import { chatDB } from './db';
import { userDB } from './userDB';
import { chatListCache } from './chatListCache';
import { chatSyncService } from './chatSyncService';
import { embedStore } from './embedStore';
import { encryptWithChatKey } from './cryptoService';
import { chatKeyManager } from './encryption/ChatKeyManager';

export interface InspirationChatDraft {
    inspiration: DailyInspiration;
    chatId: string;
    messageId: string;
    chatTitle: string;
    /** Assistant message text including the embed reference or wiki link. */
    messageContent: string;
    /** Pre-stored inspiration video embed reused by the chat, if any. */
    reusedEmbedId: string | null;
    followUpSuggestions: string[];
    /** Unix seconds when the preview was opened. */
    now: number;
}

/** Follow-up suggestions for an inspiration chat: the LLM ones, else a topic fallback. */
export function inspirationFollowUpSuggestions(inspiration: DailyInspiration): string[] {
    const llmSuggestions = inspiration.follow_up_suggestions;
    if (Array.isArray(llmSuggestions) && llmSuggestions.length > 0) return llmSuggestions;
    const topicLabel = inspiration.title
        ?? (inspiration.phrase ? inspiration.phrase.split('.')[0] : null)
        ?? inspiration.category.replace(/_/g, ' ');
    return [
        `Tell me more about ${topicLabel}`,
        `What are the practical implications of this?`,
        `What should I explore next about ${topicLabel}?`,
    ];
}

/** Persists and syncs the inspiration chat; returns the stored chat record. */
export async function saveInspirationChat(draft: InspirationChatDraft): Promise<Chat> {
    const { inspiration, chatId, messageId, chatTitle, messageContent, reusedEmbedId, now } = draft;
    const { chatKey, encryptedChatKey } = await chatKeyManager.createAndPersistKeyLocked(chatId);
    const encryptedTitle = await encryptWithChatKey(chatTitle, chatKey);
    const encryptedContent = await encryptWithChatKey(messageContent, chatKey);
    const encryptedCategory = await encryptWithChatKey(inspiration.category, chatKey);
    const encryptedFollowUpSuggestions = await encryptWithChatKey(
        JSON.stringify(draft.followUpSuggestions),
        chatKey,
    );
    let inspirationEmbedForSync: InspirationEmbedData | undefined;

    // title_v and messages_v are 1: the chat has its title and first message at
    // creation, matching what sync_inspiration_chat sends (see sendSyncInspirationChatImpl).
    const newChat = {
        chat_id: chatId,
        title: chatTitle,
        encrypted_title: encryptedTitle,
        created_at: now,
        updated_at: now,
        messages_v: 1,
        title_v: 1,
        last_edited_overall_timestamp: now,
        unread_count: 0,
        encrypted_chat_key: encryptedChatKey,
        encrypted_category: encryptedCategory,
        category: inspiration.category,
        ...(encryptedFollowUpSuggestions
            ? { encrypted_follow_up_request_suggestions: encryptedFollowUpSuggestions }
            : {}),
    } as Chat;
    await chatDB.updateChat(newChat);

    const assistantMessage = {
        message_id: messageId,
        chat_id: chatId,
        role: 'assistant' as const,
        content: messageContent,
        encrypted_content: encryptedContent,
        encrypted_category: encryptedCategory,
        category: inspiration.category,
        created_at: now,
        status: 'synced' as const,
    };
    await chatDB.saveMessage(assistantMessage as Message);
    console.info(`[InspirationChatSave] Saved inspiration chat ${chatId} with message ${messageId}`);

    // ── Add chat key wrapper + update hashed_chat_id in Directus ──
    // If we reused a pre-stored inspiration embed, associate it with the
    // newly created chat so the phased sync pipeline (which queries
    // embed_keys by hashed_chat_id) can deliver the key to other devices.
    // This is the same pattern used by normal embeds in handleSendEmbedDataImpl().
    if (reusedEmbedId) {
        try {
            const { computeSHA256 } = await import('../message_parsing/utils');
            const {
                generateEmbedKey,
                wrapEmbedKeyWithChatKey,
                wrapEmbedKeyWithMasterKey,
                encryptWithEmbedKey,
            } = await import('./cryptoService');
            const {
                sendStoreEmbedImpl,
            } = await import('./chatSyncServiceSenders');

            const profile = await userDB.getUserProfile();
            const currentUserId = profile?.user_id || '';
            const hashedChatId = await computeSHA256(chatId);
            const hashedEmbedId = await computeSHA256(reusedEmbedId);
            const hashedMessageId = await computeSHA256(messageId);
            const hashedUserId = await computeSHA256(currentUserId);

            // Retrieve the existing embed key from cache (set by persistInspirations).
            // If not in cache (e.g., page reload), first try to recover it from
            // IndexedDB via the master key wrapper that persistInspirations stored.
            // Only generate a fresh key (and re-encrypt the content) when BOTH the
            // memory cache AND IndexedDB are empty — e.g. after clearing browser data.
            //
            // Why this matters: if we generate a new key while the existing
            // encrypted_content in IndexedDB/Directus was written with the old key,
            // we write the new key into the cache before completing re-encryption.
            // Any embed render that fires in the window between setEmbedKeyInCache()
            // and sendStoreEmbedImpl() will try to decrypt old ciphertext with the
            // new key → AES-GCM auth tag mismatch → embed shows "Error" status.
            let embedKeyForWrap = embedStore.getEmbedKeyFromCache(reusedEmbedId);
            let needsReEncrypt = false;

            if (!embedKeyForWrap) {
                // Cache miss (e.g. tab reload wiped the in-memory embedKeyCache).
                // Try to unwrap the existing master key wrapper from IndexedDB.
                // getEmbedKey() checks IndexedDB and unwraps via the master key —
                // if this succeeds we can use the original key and skip re-encryption,
                // keeping the already-stored encrypted_content consistent.
                console.info(
                    `[InspirationChatSave] Embed key not in cache for ${reusedEmbedId} — trying IndexedDB recovery`,
                );
                const recoveredKey = await embedStore.getEmbedKey(reusedEmbedId, undefined);
                if (recoveredKey) {
                    embedKeyForWrap = recoveredKey;
                    console.info(
                        `[InspirationChatSave] ✅ Recovered embed key from IndexedDB for ${reusedEmbedId} — no re-encryption needed`,
                    );
                } else {
                    // IndexedDB also empty (e.g., browser data cleared or first-time
                    // cross-device). Generate a fresh key and re-encrypt the content
                    // so the new key wrapper and the stored ciphertext are in sync.
                    console.info(
                        `[InspirationChatSave] IndexedDB recovery failed for ${reusedEmbedId} — generating fresh key and re-encrypting`,
                    );
                    embedKeyForWrap = generateEmbedKey();
                    needsReEncrypt = true;
                }
            }

            // Create a chat key wrapper (this is what was missing before)
            const wrappedChatKey = await wrapEmbedKeyWithChatKey(embedKeyForWrap, chatKey);

            // Also create/refresh the master key wrapper
            const wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKeyForWrap);

            // Cache the embed key for local decryption
            embedStore.setEmbedKeyInCache(reusedEmbedId, embedKeyForWrap, undefined);

            const embedKeyTimestamp = Math.floor(Date.now() / 1000);

            // Store BOTH key wrappers (master + chat) locally and on server
            const embedKeysForStorage: import('./embedStore').EmbedKeyEntry[] = [
                {
                    hashed_embed_id: hashedEmbedId,
                    key_type: 'master',
                    hashed_chat_id: null,
                    encrypted_embed_key: wrappedMasterKey,
                    hashed_user_id: hashedUserId,
                    created_at: embedKeyTimestamp,
                },
                {
                    hashed_embed_id: hashedEmbedId,
                    key_type: 'chat',
                    hashed_chat_id: hashedChatId,
                    encrypted_embed_key: wrappedChatKey,
                    hashed_user_id: hashedUserId,
                    created_at: embedKeyTimestamp,
                },
            ];
            await embedStore.storeEmbedKeys(embedKeysForStorage);

            const syncService = chatSyncService;
            // Publish a complete encrypted head before its new chat wrapper.
            // The offline sender queues both until the canonical receipts arrive.
            const embedUpdatePayload: Record<string, unknown> = {
                embed_id: reusedEmbedId,
                status: 'finished',
                hashed_chat_id: hashedChatId,
                hashed_message_id: hashedMessageId,
                hashed_user_id: hashedUserId,
                is_private: false,
                is_shared: false,
                created_at: embedKeyTimestamp,
                updated_at: embedKeyTimestamp,
            };

            if (inspiration.video) {
                const video = inspiration.video;
                const videoUrl = `https://www.youtube.com/watch?v=${video.youtube_id}`;
                let durationFmt: string | null = null;
                if (video.duration_seconds != null) {
                    const m = Math.floor(video.duration_seconds / 60);
                    const s = video.duration_seconds % 60;
                    durationFmt = `${m}:${s.toString().padStart(2, '0')}`;
                }
                const embedContentObj = {
                    url: videoUrl,
                    video_id: video.youtube_id,
                    title: video.title || null,
                    description: null,
                    channel_name: video.channel_name || null,
                    channel_id: null,
                    channel_thumbnail: null,
                    thumbnail: video.thumbnail_url || null,
                    duration_seconds: video.duration_seconds ?? null,
                    duration_formatted: durationFmt,
                    view_count: video.view_count ?? null,
                    like_count: null,
                    published_at: video.published_at || null,
                    fetched_at: new Date().toISOString(),
                };
                let toonStr: string;
                try {
                    toonStr = (await import('@toon-format/toon')).encode(embedContentObj);
                } catch {
                    toonStr = JSON.stringify(embedContentObj);
                }

                const encContent = await encryptWithEmbedKey(toonStr, embedKeyForWrap);
                const encType = await encryptWithEmbedKey('video', embedKeyForWrap);
                const encPreview = await encryptWithEmbedKey(
                    video.title || 'YouTube Video', embedKeyForWrap,
                );
                if (!encContent || !encType) {
                    throw new Error('Failed to encrypt reused inspiration embed before publishing its chat wrapper');
                }
                embedUpdatePayload.encrypted_content = encContent;
                embedUpdatePayload.encrypted_type = encType;
                if (encPreview) embedUpdatePayload.encrypted_text_preview = encPreview;
            }

            if (syncService) {
                await sendStoreEmbedImpl(
                    syncService,
                    embedUpdatePayload as unknown as import('../types/chat').StoreEmbedPayload,
                    { keys: embedKeysForStorage.map((key) => ({ ...key })) },
                );
            }

            console.info(
                `[InspirationChatSave] ✅ Associated inspiration embed ${reusedEmbedId} with chat ${chatId} ` +
                `(added chat key wrapper + updated hashed_chat_id in Directus)` +
                (needsReEncrypt ? ' [re-encrypted with fresh key]' : ''),
            );

            // ── Capture embed data for cross-device sync ─────────────────
            // Build the encrypted embed payload so sendSyncInspirationChat
            // can include it in the broadcast. This lets the receiving
            // device store the embed + keys immediately — no Directus
            // round-trip required. Without this, a quick device switch
            // after opening an inspiration often fails because store_embed
            // hasn't reached Directus yet when the second device calls
            // request_embed.
            try {
                // Get or create the encrypted embed fields for the sync payload.
                // The canonical head was encrypted before its wrappers were queued.
                let encEmbedContent = embedUpdatePayload.encrypted_content as string | undefined;
                let encEmbedType = embedUpdatePayload.encrypted_type as string | undefined;
                let encEmbedPreview = embedUpdatePayload.encrypted_text_preview as string | undefined;

                if (!encEmbedContent && inspiration.video) {
                    // Normal path (no re-encrypt needed): encrypt the embed content
                    // using the original embed key so the receiving device can decrypt.
                    const video = inspiration.video;
                    const videoUrl = `https://www.youtube.com/watch?v=${video.youtube_id}`;
                    let dFmt: string | null = null;
                    if (video.duration_seconds != null) {
                        const mn = Math.floor(video.duration_seconds / 60);
                        const sc = video.duration_seconds % 60;
                        dFmt = `${mn}:${sc.toString().padStart(2, '0')}`;
                    }
                    const embedObj = {
                        url: videoUrl,
                        video_id: video.youtube_id,
                        title: video.title || null,
                        description: null,
                        channel_name: video.channel_name || null,
                        channel_id: null,
                        channel_thumbnail: null,
                        thumbnail: video.thumbnail_url || null,
                        duration_seconds: video.duration_seconds ?? null,
                        duration_formatted: dFmt,
                        view_count: video.view_count ?? null,
                        like_count: null,
                        published_at: video.published_at || null,
                        fetched_at: new Date().toISOString(),
                    };
                    let tStr: string;
                    try {
                        tStr = (await import('@toon-format/toon')).encode(embedObj);
                    } catch {
                        tStr = JSON.stringify(embedObj);
                    }

                    encEmbedContent = await encryptWithEmbedKey(tStr, embedKeyForWrap) ?? undefined;
                    encEmbedType = await encryptWithEmbedKey('video', embedKeyForWrap) ?? undefined;
                    encEmbedPreview = await encryptWithEmbedKey(
                        video.title || 'YouTube Video', embedKeyForWrap,
                    ) ?? undefined;
                }

                if (encEmbedContent && encEmbedType) {
                    inspirationEmbedForSync = {
                        embed_id: reusedEmbedId,
                        encrypted_content: encEmbedContent,
                        encrypted_type: encEmbedType,
                        encrypted_text_preview: encEmbedPreview || '',
                        embed_keys: embedKeysForStorage,
                    };
                    console.info(
                        `[InspirationChatSave] Prepared inspiration embed ${reusedEmbedId} for cross-device sync`,
                    );
                }
            } catch (embedSyncErr) {
                // Non-fatal: second device falls back to request_embed
                console.warn(
                    '[InspirationChatSave] Failed to prepare embed for cross-device sync (non-fatal):',
                    embedSyncErr,
                );
            }
        } catch (keyErr) {
            // Non-fatal: the embed is stored locally and works on this device.
            // Other devices can use the request_embed safety net to get the key.
            console.error(
                '[InspirationChatSave] Failed to create chat key wrapper for inspiration embed (non-fatal):',
                keyErr,
            );
        }
    }

    // Only now is the inspiration opened: it leaves the start row (which shows
    // today's unopened inspirations) and its card opens this saved chat next time.
    const { dailyInspirationStore: inspirationStore } = await import('../stores/dailyInspirationStore');
    const { markInspirationOpenedInIndexedDB, markInspirationOpenedOnAPI } = await import('./dailyInspirationDB');

    // Hashed chat ID used as the opened_chat_id reference
    const openedChatId = chatId;

    // Update the Svelte store immediately (optimistic update)
    inspirationStore.markOpened(inspiration.inspiration_id, openedChatId);

    // Persist to IndexedDB and API in the background (non-blocking, non-fatal)
    markInspirationOpenedInIndexedDB(inspiration.inspiration_id, openedChatId).catch((err: unknown) => {
        console.error('[InspirationChatSave] Failed to mark inspiration opened in IndexedDB:', err);
    });
    markInspirationOpenedOnAPI(
        inspiration.inspiration_id,
        openedChatId,
        inspiration.video?.youtube_id,
    ).catch((err: unknown) => {
        console.error('[InspirationChatSave] Failed to mark inspiration opened on API:', err);
    });

    chatListCache.upsertChat(newChat);
    window.dispatchEvent(new CustomEvent('localChatListChanged', {
        bubbles: true,
        composed: true,
        detail: { reason: 'inspiration_chat_created', chatId },
    }));
    window.dispatchEvent(new CustomEvent('globalChatSelected', {
        bubbles: true,
        composed: true,
        detail: { chatId },
    }));

    // ── Cross-device sync ────────────────────────────────────────────────
    // The chat was created locally (IndexedDB only). Sync it to the server
    // so that other devices can see it via phased sync or the broadcast.
    // 1. Update last_opened on the server (resume card on other devices).
    // 2. Send the encrypted chat + message for cross-device broadcast.
    try {
        // Notify server of the active chat (updates last_opened in Redis + Directus)
        chatSyncService.sendSetActiveChat(chatId);

        // Sync the full chat + first message for cross-device visibility.
        // Include the inspiration embed data + keys so other devices can
        // store and decrypt the embed immediately without a Directus round-trip.
        if (encryptedChatKey) {
            await chatSyncService.sendSyncInspirationChat(
                chatId,
                messageId,
                messageContent,
                inspiration.category,
                encryptedTitle,
                encryptedCategory,
                encryptedContent,
                encryptedChatKey,
                now,
                encryptedFollowUpSuggestions ?? undefined,
                inspirationEmbedForSync,
            );
        } else {
            console.warn('[InspirationChatSave] Could not encrypt chat key for inspiration chat sync — chat will sync on next phased sync');
        }
    } catch (syncErr) {
        // Non-fatal — chat still works locally, will sync eventually
        console.warn('[InspirationChatSave] Failed to sync inspiration chat to server:', syncErr);
    }

    return newChat;
}
