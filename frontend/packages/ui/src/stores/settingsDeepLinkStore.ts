import { writable } from 'svelte/store';

/**
 * Store that allows components outside of the settings menu to request 
 * the settings menu to open with a specific settings path.
 * 
 * Usage:
 * - Set this with a path string like 'privacy' or 'interface' to open settings to that page
 * - The store will be reset to null after the settings menu handles the deep link
 */
export const settingsDeepLink = writable<string | null>(null);
