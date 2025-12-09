// frontend/packages/ui/src/stores/videoIframeStore.ts
/**
 * Store for managing the standalone VideoIframe component state.
 * 
 * This store manages:
 * 1. Whether the video iframe is active (playing)
 * 2. Video metadata (URL, title, videoId, embedUrl, thumbnailUrl)
 * 3. PiP mode state - controls CSS-based positioning (not DOM movement)
 * 
 * Architecture:
 * - VideoIframe is ALWAYS rendered in ActiveChat (never moved between parents)
 * - PiP mode is achieved via CSS classes that animate position/size
 * - The iframe is never destroyed or reloaded during PiP transitions
 * - Only CSS changes (position, size) create smooth animations
 */

import { writable } from 'svelte/store';

export interface VideoIframeState {
    /** Whether VideoIframe is currently active/visible (video is playing or about to play) */
    isActive: boolean;
    /** Whether the video is in Picture-in-Picture mode (small, top-right) */
    isPipMode: boolean;
    /** Whether the video is fading out (closing animation) */
    isClosing: boolean;
    /** Video URL */
    url?: string;
    /** Video title */
    title?: string;
    /** Video ID (e.g., YouTube video ID) */
    videoId?: string;
    /** Embed URL for the iframe */
    embedUrl?: string;
    /** Thumbnail URL (not used by VideoIframe, but kept for reference) */
    thumbnailUrl?: string;
    /** Reference to the iframe element (for state preservation checks) */
    iframeElement?: HTMLIFrameElement | null;
    /** Reference to the iframe wrapper element (for state preservation checks) */
    iframeWrapperElement?: HTMLDivElement | null;
}

const initialState: VideoIframeState = {
    isActive: false,
    isPipMode: false,
    isClosing: false,
    url: undefined,
    title: undefined,
    videoId: undefined,
    embedUrl: undefined,
    thumbnailUrl: undefined,
    iframeElement: undefined,
    iframeWrapperElement: undefined
};

const { subscribe, set, update } = writable<VideoIframeState>(initialState);

export const videoIframeStore = {
    subscribe,
    
    /**
     * Start playing video - activates the iframe with video data.
     * Called when user clicks the play button in VideoEmbedFullscreen.
     * 
     * @param data - Video data to play
     */
    playVideo: (data: {
        url: string;
        title?: string;
        videoId?: string;
        embedUrl?: string;
        thumbnailUrl?: string;
    }) => {
        console.debug('[VideoIframeStore] Playing video:', data.url);
        set({
            isActive: true,
            isPipMode: false, // Start in fullscreen mode (centered, large)
            isClosing: false, // Not closing
            url: data.url,
            title: data.title,
            videoId: data.videoId,
            embedUrl: data.embedUrl,
            thumbnailUrl: data.thumbnailUrl,
            iframeElement: undefined,
            iframeWrapperElement: undefined
        });
    },
    
    /**
     * Open VideoIframe with video data (alias for playVideo for backwards compatibility)
     * @deprecated Use playVideo instead
     */
    open: (data: {
        url: string;
        title?: string;
        videoId?: string;
        embedUrl?: string;
        thumbnailUrl?: string;
    }) => {
        // Keep store open but don't auto-play - the iframe will show thumbnail
        // This is called when VideoEmbedFullscreen opens
        console.debug('[VideoIframeStore] Opening (preparing video data):', data.url);
        update(state => ({
            ...state,
            url: data.url,
            title: data.title,
            videoId: data.videoId,
            embedUrl: data.embedUrl,
            thumbnailUrl: data.thumbnailUrl
        }));
    },
    
    /**
     * Enter PiP mode - switches to small top-right position via CSS.
     * The iframe is NOT moved or recreated - only CSS classes change.
     */
    enterPipMode: () => {
        console.debug('[VideoIframeStore] Entering PiP mode');
        update(state => ({
            ...state,
            isPipMode: true
        }));
    },
    
    /**
     * Exit PiP mode - switches back to centered fullscreen position via CSS.
     * The iframe is NOT moved or recreated - only CSS classes change.
     */
    exitPipMode: () => {
        console.debug('[VideoIframeStore] Exiting PiP mode');
        update(state => ({
            ...state,
            isPipMode: false
        }));
    },
    
    /**
     * Close VideoIframe - stops video and hides the iframe.
     * Called when user closes the video entirely.
     */
    close: () => {
        console.debug('[VideoIframeStore] Closing VideoIframe');
        set(initialState);
    },
    
    /**
     * Close VideoIframe with fade-out animation.
     * Sets isClosing to true, waits for animation, then clears state.
     * 
     * @param fadeOutDuration - Duration of fade-out in ms (default 300ms)
     */
    closeWithFadeOut: (fadeOutDuration: number = 300) => {
        console.debug('[VideoIframeStore] Closing VideoIframe with fade-out');
        
        // Set closing state to trigger CSS fade-out
        update(state => ({
            ...state,
            isClosing: true
        }));
        
        // After animation completes, clear all state
        setTimeout(() => {
            console.debug('[VideoIframeStore] Fade-out complete, clearing state');
            set(initialState);
        }, fadeOutDuration);
    },
    
    /**
     * Update iframe references (for state preservation checks)
     * These refs are used to verify the iframe hasn't been recreated.
     */
    updateIframeRefs: (iframeElement: HTMLIFrameElement | null | undefined, iframeWrapperElement: HTMLDivElement | null | undefined) => {
        update(state => ({
            ...state,
            iframeElement: iframeElement ?? null,
            iframeWrapperElement: iframeWrapperElement ?? null
        }));
    },
    
    /**
     * Clear all state (alias for close)
     */
    clear: () => {
        console.debug('[VideoIframeStore] Clearing all state');
        set(initialState);
    }
};
