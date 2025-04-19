import { writable } from 'svelte/store';

/**
 * Writable store to track whether team features are enabled in settings.
 */
export const teamEnabled = writable<boolean>(true);