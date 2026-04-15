/**
 * introVideoFullscreenStore.ts
 *
 * Signals that the intro video (for-everyone chat header) fullscreen should
 * be open or closed. ChatHeader sets it; ActiveChat renders the fullscreen.
 *
 * Kept minimal intentionally — no embed_id, no DB lookup.
 * The video URL and start time come from the DemoChat metadata and are
 * passed directly through the component tree rather than stored here.
 */

import { writable } from 'svelte/store';

export const introVideoFullscreenStore = writable(false);

export function openIntroVideoFullscreen() {
  introVideoFullscreenStore.set(true);
}

export function closeIntroVideoFullscreen() {
  introVideoFullscreenStore.set(false);
}
