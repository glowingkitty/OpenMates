import { writable } from 'svelte/store';

/**
 * Store to track whether an invite code is required for signup
 * Default to false (open signup) - the actual value will be set by the backend
 * via the session endpoint response
 */
export const requireInviteCode = writable(false);
