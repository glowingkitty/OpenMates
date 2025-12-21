/**
 * Active Embed Store
 * 
 * Maintains the currently active/opened embed ID across component lifecycle.
 * This ensures embeds can be opened from URL hash and shared/bookmarked.
 * 
 * Also manages URL hash to allow users to share/bookmark specific embeds.
 * Format: #embed-id={embedId}
 */

import { writable } from 'svelte/store';
import { browser } from '$app/environment';

/**
 * Flag to prevent hashchange events from triggering when we programmatically update the hash
 * This prevents infinite loops when setActiveEmbed updates the hash
 * Uses a timestamp to track when we last updated the hash programmatically
 */
let lastProgrammaticEmbedHashUpdate = 0;
const PROGRAMMATIC_UPDATE_WINDOW_MS = 100; // Window to ignore hashchange events after programmatic update

/**
 * Update the URL hash with the embed ID
 * Format: #embed-id={embedId}
 * Only updates if the hash doesn't already match to prevent unnecessary hashchange events
 */
function updateUrlHash(embedId: string | null) {
	if (!browser) return; // Only update URL in browser environment
	
	const currentHash = window.location.hash;
	const expectedHash = embedId ? `#embed-id=${embedId}` : '';
	
	// Only update if hash doesn't already match (prevents unnecessary hashchange events)
	if (currentHash === expectedHash) {
		return; // Hash already matches, no update needed
	}
	
	// Record timestamp of programmatic update
	lastProgrammaticEmbedHashUpdate = Date.now();
	
	if (embedId) {
		// Set hash to #embed-id={embedId}
		window.location.hash = `embed-id=${embedId}`;
	} else {
		// Clear hash if no embed is selected
		// Use replaceState to avoid adding to browser history
		if (window.location.hash.startsWith('#embed-id=')) {
			window.history.replaceState(null, '', window.location.pathname + window.location.search);
		}
	}
}

/**
 * Check if a hashchange event was triggered by our programmatic update
 * This allows hashchange handlers to ignore programmatic updates
 * Uses a time window to account for async hashchange event firing
 */
export function isProgrammaticEmbedHashUpdate(): boolean {
	const timeSinceUpdate = Date.now() - lastProgrammaticEmbedHashUpdate;
	return timeSinceUpdate < PROGRAMMATIC_UPDATE_WINDOW_MS;
}

/**
 * Read embed ID from URL hash
 * Returns the embed ID if found, null otherwise
 * Supports both #embed-id= and #embed_id= formats for backward compatibility
 */
function readEmbedIdFromHash(): string | null {
	if (!browser) return null;
	
	const hash = window.location.hash;
	if (hash.startsWith('#embed-id=')) {
		const embedId = hash.substring('#embed-id='.length);
		// Handle cases where there might be additional query params (e.g., #embed-id=xxx&fullscreen=true)
		const embedIdOnly = embedId.split('&')[0].split('?')[0];
		return embedIdOnly || null;
	}
	
	// Support legacy format for backward compatibility
	if (hash.startsWith('#embed_id=')) {
		const embedId = hash.substring('#embed_id='.length);
		const embedIdOnly = embedId.split('&')[0].split('?')[0];
		return embedIdOnly || null;
	}
	
	return null;
}

/**
 * Store for tracking the currently active embed ID
 * Persists across component mount/unmount cycles
 * Also syncs with URL hash for shareable/bookmarkable embed links
 */
function createActiveEmbedStore() {
	// Initialize with embed ID from URL hash if present
	const initialEmbedId = readEmbedIdFromHash();
	const { subscribe, set, update } = writable<string | null>(initialEmbedId);

	return {
		subscribe,
		
		/**
		 * Set the currently active embed ID
		 * Also updates the URL hash to allow sharing/bookmarking
		 */
		setActiveEmbed: (embedId: string | null) => {
			set(embedId);
			updateUrlHash(embedId);
		},
		
		/**
		 * Clear the active embed (no embed selected)
		 * Also clears the URL hash
		 */
		clearActiveEmbed: () => {
			set(null);
			updateUrlHash(null);
		},
		
		/**
		 * Get the current active embed ID (for one-time reads)
		 */
		get: () => {
			let value: string | null = null;
			subscribe(v => value = v)();
			return value;
		},
		
		/**
		 * Get embed ID from URL hash (for initialization)
		 * This is called during app initialization to restore embed from URL
		 */
		getEmbedIdFromHash: () => {
			return readEmbedIdFromHash();
		}
	};
}

export const activeEmbedStore = createActiveEmbedStore();



