import { writable } from 'svelte/store';

// Keep an explicit deep-link focus request until the real composer mounts.
// This contains no message text and never clears, prefills, or sends a draft.
export const composerFocusRequested = writable(false);
