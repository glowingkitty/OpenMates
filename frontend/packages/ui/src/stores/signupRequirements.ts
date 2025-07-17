import { writable } from 'svelte/store';

/**
 * Store to track whether an invite code is required for signup
 * Default to true for backward compatibility
 */
export const requireInviteCode = writable(true);
