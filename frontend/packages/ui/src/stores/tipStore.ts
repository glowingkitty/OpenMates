// frontend/packages/ui/src/stores/tipStore.ts
/**
 * Store for managing tip dialog state.
 * Used to pass tip data (ownerId, contentType, videoUrl) to SettingsTip component.
 */

import { writable } from 'svelte/store';

export interface TipData {
    ownerId?: string;  // Channel ID for videos, domain for websites
    contentType?: 'video' | 'website';
    videoUrl?: string;  // Video URL to extract channel ID from
}

const initialState: TipData = {
    ownerId: undefined,
    contentType: undefined,
    videoUrl: undefined
};

const { subscribe, set, update } = writable<TipData>(initialState);

export const tipStore = {
    subscribe,
    /**
     * Set tip data for the tip dialog
     */
    setTipData: (data: TipData) => {
        set(data);
    },
    /**
     * Clear tip data
     */
    clearTipData: () => {
        set(initialState);
    }
};
