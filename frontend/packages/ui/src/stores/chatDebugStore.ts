/**
 * Chat debug mode store.
 *
 * Controls whether messages render with full formatting (embeds, markdown, etc.)
 * or are displayed as raw plain text so developers can inspect JSON embed
 * placeholders, missing content, and other rendering issues.
 *
 * Architecture: global writable store; both ChatContextMenu and
 * MessageContextMenu toggle this flag. ChatMessage.svelte reads it to decide
 * whether to pass content to ReadOnlyMessage or render it as a <pre> block.
 *
 * To add more debug features in the future, extend the ChatDebugState
 * interface and initialise the new field to its default "off" value.
 */

import { writable } from 'svelte/store';

export interface ChatDebugState {
    /** When true, messages show raw plain text instead of rendered content. */
    rawTextMode: boolean;

    // Future debug flags can be added here, e.g.:
    // showEmbedBoundaries: boolean;
    // disableEncryption: boolean;
}

const INITIAL_STATE: ChatDebugState = {
    rawTextMode: false,
};

function createChatDebugStore() {
    const { subscribe, update, set } = writable<ChatDebugState>(INITIAL_STATE);

    return {
        subscribe,

        /** Toggle the entire debug mode on/off (resets all flags to their default state). */
        toggle(): void {
            update(state => {
                const nextActive = !state.rawTextMode;
                return { ...INITIAL_STATE, rawTextMode: nextActive };
            });
        },

        /** Reset all debug flags to their off defaults. */
        reset(): void {
            set(INITIAL_STATE);
        },
    };
}

export const chatDebugStore = createChatDebugStore();
