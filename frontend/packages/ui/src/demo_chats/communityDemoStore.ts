// frontend/packages/ui/src/demo_chats/communityDemoStore.ts
// In-memory store for community demo chats with IndexedDB caching for offline support.
//
// ARCHITECTURE DECISION:
// Community demo chats are:
// 1. Cached in IndexedDB (demo_chats_db) for offline support
// 2. Loaded into memory for fast access during the session
// 3. Never deleted during logout (unlike regular chats_db)
// 4. Fetched from server when cache is empty/stale
//
// This provides full offline support while avoiding database blocking issues during logout.

import { writable, get } from 'svelte/store';
import type { Chat, Message } from '../types/chat';
import { demoChatsDB } from '../services/demoChatsDB';
import type { DemoEmbed } from '../services/demoChatsDB';

// ============================================================================
// TYPES
// ============================================================================

/**
 * Community demo chat data structure
 * Contains the chat metadata, messages, and embeds
 */
interface CommunityDemoData {
    chat: Chat;
    messages: Message[];
    embeds: DemoEmbed[];  // Cleartext embeds for community demos
}

/**
 * Store state for community demo chats
 * Keyed by chat_id (e.g., "demo-1", "demo-2")
 */
interface CommunityDemoStoreState {
    chats: Map<string, CommunityDemoData>;
    loaded: boolean; // True after initial load attempt (success or failure)
    loading: boolean; // True while fetching from server
    cacheLoaded: boolean; // True after IndexedDB cache has been loaded into memory
}

// ============================================================================
// STORE IMPLEMENTATION
// ============================================================================

/**
 * Initial state for the community demo store
 */
const initialState: CommunityDemoStoreState = {
    chats: new Map(),
    loaded: false,
    loading: false,
    cacheLoaded: false
};

/**
 * Writable store for community demo chats
 * Use the exported functions below to interact with this store
 */
const store = writable<CommunityDemoStoreState>(initialState);

// ============================================================================
// PUBLIC API
// ============================================================================

/**
 * Add or update a community demo chat in the store and cache it in IndexedDB
 * @param demoId - The server demo ID (e.g., "demo-1")
 * @param chat - The Chat object
 * @param messages - Array of Message objects for this chat
 * @param contentHash - SHA256 hash of content for change detection (optional)
 * @param embeds - Array of DemoEmbed objects for this chat (optional)
 */
export async function addCommunityDemo(demoId: string, chat: Chat, messages: Message[], contentHash: string = '', embeds: DemoEmbed[] = []): Promise<void> {
    // Add to in-memory store first (includes embeds)
    store.update(state => {
        const newChats = new Map(state.chats);
        newChats.set(chat.chat_id, { chat, messages, embeds });
        console.debug(`[CommunityDemoStore] Added community demo: ${demoId} (${chat.chat_id}) with ${messages.length} messages and ${embeds.length} embeds`);
        return { ...state, chats: newChats };
    });

    // Cache in IndexedDB for offline support (don't await to avoid blocking UI)
    try {
        await demoChatsDB.storeDemoChat(demoId, chat, messages, contentHash, embeds);
        console.debug(`[CommunityDemoStore] Cached community demo ${demoId} in IndexedDB (hash: ${contentHash.slice(0, 16)}...)`);
    } catch (error) {
        console.error(`[CommunityDemoStore] Failed to cache community demo ${demoId}:`, error);
        // Don't throw - in-memory store is still working
    }
}

/**
 * Get all content hashes for cached demo chats
 * Used for change detection when fetching demo list from server
 * @returns Map of demo_id to content_hash
 */
export async function getLocalContentHashes(): Promise<Map<string, string>> {
    try {
        return await demoChatsDB.getAllContentHashes();
    } catch (error) {
        console.error('[CommunityDemoStore] Failed to get content hashes:', error);
        return new Map();
    }
}

/**
 * Get a community demo chat by ID
 * @param chatId - The chat ID to look up
 * @returns The Chat object or null if not found
 */
export function getCommunityDemoChat(chatId: string): Chat | null {
    const state = get(store);
    const data = state.chats.get(chatId);
    return data?.chat || null;
}

/**
 * Get messages for a community demo chat
 * @param chatId - The chat ID to look up
 * @returns Array of Message objects or empty array if not found
 */
export function getCommunityDemoMessages(chatId: string): Message[] {
    const state = get(store);
    const data = state.chats.get(chatId);
    return data?.messages || [];
}

/**
 * Get embeds for a community demo chat
 * Returns cleartext embed data for rendering in demo chats
 * @param chatId - The chat ID to look up
 * @returns Array of DemoEmbed objects or empty array if not found
 */
export function getCommunityDemoEmbeds(chatId: string): DemoEmbed[] {
    const state = get(store);
    const data = state.chats.get(chatId);
    return data?.embeds || [];
}

/**
 * Get a specific embed by ID from community demo store
 * @param embedId - The embed ID to look up
 * @returns The DemoEmbed object or null if not found
 */
export function getCommunityDemoEmbed(embedId: string): DemoEmbed | null {
    const state = get(store);
    // Convert MapIterator to Array to avoid --downlevelIteration requirement
    const chatDataArray = Array.from(state.chats.values());
    for (const data of chatDataArray) {
        const embed = data.embeds.find(e => e.embed_id === embedId);
        if (embed) {
            return embed;
        }
    }
    return null;
}

/**
 * Get all community demo chats as Chat objects
 * @returns Array of all community demo Chat objects
 */
export function getAllCommunityDemoChats(): Chat[] {
    const state = get(store);
    return Array.from(state.chats.values()).map(data => data.chat);
}

/**
 * Check if a chat ID is a community demo chat
 * Community demos have IDs like "demo-1", "demo-2", etc. (from server)
 * Static demos have IDs like "demo-welcome", "demo-different" (from code)
 * @param chatId - The chat ID to check
 * @returns True if this is a community demo (in our store)
 */
export function isCommunityDemo(chatId: string): boolean {
    const state = get(store);
    return state.chats.has(chatId);
}

/**
 * Load community demos from IndexedDB cache into memory
 * This provides offline support - cached demos are available immediately
 * Loads messages and embeds for each cached demo chat
 */
export async function loadFromCache(): Promise<void> {
    const currentState = get(store);
    if (currentState.cacheLoaded) {
        return; // Already loaded
    }

    try {
        console.debug('[CommunityDemoStore] Loading community demos from IndexedDB cache...');
        const cachedChats = await demoChatsDB.getAllDemoChats();

        if (cachedChats.length > 0) {
            // Load each cached chat with its messages and embeds
            const newChats = new Map();
            let totalEmbeds = 0;

            for (const chat of cachedChats) {
                const messages = await demoChatsDB.getDemoMessages(chat.chat_id);
                const embeds = await demoChatsDB.getDemoEmbeds(chat.chat_id);
                newChats.set(chat.chat_id, { chat, messages, embeds });
                totalEmbeds += embeds.length;
            }

            store.update(state => ({
                ...state,
                chats: newChats,
                cacheLoaded: true
            }));

            console.debug(`[CommunityDemoStore] Loaded ${cachedChats.length} community demos with ${totalEmbeds} embeds from cache`);
        } else {
            // No cached chats, but cache is still "loaded" (empty)
            store.update(state => ({ ...state, cacheLoaded: true }));
            console.debug('[CommunityDemoStore] No community demos in cache');
        }
    } catch (error) {
        console.error('[CommunityDemoStore] Error loading from cache:', error);
        // Mark as loaded even on error to avoid infinite retries
        store.update(state => ({ ...state, cacheLoaded: true }));
    }
}

/**
 * Check if community demos have been loaded (or attempted to load)
 * @returns True if the initial load has been attempted
 */
export function isLoaded(): boolean {
    return get(store).loaded;
}

/**
 * Check if cache has been loaded from IndexedDB
 * @returns True if IndexedDB cache has been loaded into memory
 */
export function isCacheLoaded(): boolean {
    return get(store).cacheLoaded;
}

/**
 * Check if community demos are currently loading
 * @returns True if currently fetching from server
 */
export function isLoading(): boolean {
    return get(store).loading;
}

/**
 * Set the loading state
 * @param loading - Whether the store is currently loading
 */
export function setLoading(loading: boolean): void {
    store.update(state => ({ ...state, loading }));
}

/**
 * Mark the store as loaded (initial load complete)
 * Call this after the load attempt, regardless of success/failure
 */
export function markAsLoaded(): void {
    store.update(state => ({ ...state, loaded: true, loading: false }));
}

/**
 * Clear all community demo chats from the store
 * Used during logout or when refreshing data
 */
export function clearCommunityDemos(): void {
    console.debug('[CommunityDemoStore] Clearing all community demos');
    store.set(initialState);
}

/**
 * Get the count of community demo chats
 * @returns Number of community demos in the store
 */
export function getCommunityDemoCount(): number {
    return get(store).chats.size;
}

/**
 * Returns a promise that resolves when the store has finished its current loading process.
 * If not currently loading, resolves immediately.
 */
export async function waitForLoadingComplete(): Promise<void> {
    const currentState = get(store);
    if (!currentState.loading) {
        return;
    }

    return new Promise(resolve => {
        const unsubscribe = store.subscribe(state => {
            if (!state.loading) {
                unsubscribe();
                resolve();
            }
        });
    });
}

// ============================================================================
// REACTIVE STORE EXPORT
// ============================================================================

/**
 * Subscribe to community demo store changes
 * Useful for reactive components that need to re-render when demos are loaded
 */
export const communityDemoStore = {
    subscribe: store.subscribe,
    // Expose public API methods for convenience
    loadFromCache,
    add: addCommunityDemo,
    getChat: getCommunityDemoChat,
    getMessages: getCommunityDemoMessages,
    getEmbeds: getCommunityDemoEmbeds,
    getEmbed: getCommunityDemoEmbed,
    getAllChats: getAllCommunityDemoChats,
    isDemo: isCommunityDemo,
    isLoaded,
    isCacheLoaded,
    isLoading,
    setLoading,
    markAsLoaded,
    clear: clearCommunityDemos,
    count: getCommunityDemoCount,
    waitForLoadingComplete
};
