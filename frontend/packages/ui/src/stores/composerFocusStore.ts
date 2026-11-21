import { writable } from 'svelte/store';

// Keep an explicit deep-link focus request until the real composer mounts.
// This contains no message text and never clears, prefills, or sends a draft.
export const composerFocusRequested = writable(false);

// Ask the mounted composer to leave its expanded focus state (the draft stays).
// Inline answers such as the memory request need a stable layout: otherwise the
// first tap on them collapses the composer and the click misses its button.
export const composerDismissRequested = writable(false);
