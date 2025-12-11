/**
 * Incognito Mode Store
 *
 * Manages the incognito mode state, which determines whether new chats
 * should be created as incognito chats (not synced, not stored in Directus).
 * State is stored in sessionStorage (device-specific, cleared on tab close).
 */

import { writable } from 'svelte/store';
import { browser } from '$app/environment';

/**
 * Store for tracking incognito mode state
 * Persists in sessionStorage for the current browser tab session
 */
function createIncognitoModeStore() {
    const STORAGE_KEY = 'incognito_mode_enabled';
    const { subscribe, set: setStore, update } = writable<boolean>(false);

    // Initialize from sessionStorage on client
    if (browser) {
        const stored = sessionStorage.getItem(STORAGE_KEY);
        if (stored === 'true') {
            setStore(true);
        }
    }

    // Define set method first so toggle can reference it
    const setMethod = async (value: boolean) => {
        if (browser) {
            sessionStorage.setItem(STORAGE_KEY, String(value));
            // Update store first so UI updates immediately
            setStore(value);

            // CRITICAL: When disabling incognito mode, delete all incognito chats
            if (!value) {
                try {
                    const { incognitoChatService } = await import('../services/incognitoChatService');
                    await incognitoChatService.deleteAllChats();

                    // Dispatch event to update UI (e.g., remove from chat list)
                    if (typeof window !== 'undefined') {
                        window.dispatchEvent(new CustomEvent('incognitoChatsDeleted'));
                    }
                } catch (error) {
                    console.error('[IncognitoModeStore] Error deleting incognito chats:', error);
                    // Don't fail the set operation if deletion fails
                }
            }
        } else {
            setStore(value);
        }
    };

    return {
        subscribe,

        /**
         * Set incognito mode state
         * When disabling, deletes all incognito chats
         */
        set: setMethod,

        /**
         * Toggle incognito mode state
         * When disabling, deletes all incognito chats
         * Note: This is a convenience method that calls set() internally
         */
        toggle: async () => {
            let currentValue: boolean = false;
            subscribe(v => currentValue = v)();
            const newValue = !currentValue;
            // Call the store's set method
            await setMethod(newValue);
        },

        /**
         * Get the current incognito mode state (for one-time reads)
         */
        get: () => {
            let value: boolean = false;
            subscribe(v => value = v)();
            return value;
        }
    };
}

export const incognitoMode = createIncognitoModeStore();
