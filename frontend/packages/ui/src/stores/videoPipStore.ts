// frontend/packages/ui/src/stores/videoPipStore.ts
/**
 * Store for managing video picture-in-picture (PiP) state.
 * Handles transitioning videos between fullscreen and PiP modes
 * without reloading the video iframe.
 */

import { writable } from 'svelte/store';

export interface VideoPipState {
    /** Whether PiP mode is currently active */
    isActive: boolean;
    /** Video URL being shown in PiP */
    url?: string;
    /** Video title */
    title?: string;
    /** Video ID (e.g., YouTube video ID) */
    videoId?: string;
    /** Embed URL for the iframe */
    embedUrl?: string;
    /** Reference to the iframe element (moved, not recreated) */
    iframeElement?: HTMLIFrameElement | null;
    /** Reference to the iframe wrapper element (for positioning) */
    iframeWrapperElement?: HTMLDivElement | null;
}

const initialState: VideoPipState = {
    isActive: false,
    url: undefined,
    title: undefined,
    videoId: undefined,
    embedUrl: undefined,
    iframeElement: undefined
};

const { subscribe, set, update } = writable<VideoPipState>(initialState);

export const videoPipStore = {
    subscribe,
    /**
     * Enter PiP mode with video data
     * @param data - Video data to show in PiP
     */
    enterPip: (data: {
        url: string;
        title?: string;
        videoId?: string;
        embedUrl?: string;
        iframeElement?: HTMLIFrameElement | null;
        iframeWrapperElement?: HTMLDivElement | null;
    }) => {
        console.debug('[VideoPipStore] Entering PiP mode:', data.url);
        set({
            isActive: true,
            url: data.url,
            title: data.title,
            videoId: data.videoId,
            embedUrl: data.embedUrl,
            iframeElement: data.iframeElement,
            iframeWrapperElement: data.iframeWrapperElement
        });
    },
    /**
     * Exit PiP mode
     */
    exitPip: () => {
        console.debug('[VideoPipStore] Exiting PiP mode');
        set(initialState);
    },
    /**
     * Clear all PiP state
     */
    clear: () => {
        set(initialState);
    }
};
