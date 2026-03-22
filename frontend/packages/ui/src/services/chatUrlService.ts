/**
 * Chat URL Service
 * 
 * Manages URL-based chat navigation with privacy-first approach.
 * 
 * Current Behavior (Privacy-First):
 * - Deep linking is supported: opening a URL with #chat-id=xxx will load that chat
 * - URL is immediately cleared after loading the deep-linked chat
 * - Normal chat navigation does NOT update the URL (no automatic URL updates)
 * - This prevents accidental sharing of chat history via URL
 * 
 * Privacy Features:
 * - Uses SvelteKit's replaceState() to update URL WITHOUT adding browser history entries
 * - Hash fragments (#) are never sent to server, providing server-side privacy
 * - Combined approach: Private from both server AND browser history
 * 
 * Use Cases:
 * - Share direct links to specific chats (recipient-initiated only)
 * - Deep link to chats from external sources
 * - URL is cleared immediately after loading to prevent accidental sharing
 */

import { replaceState } from '$app/navigation';
import { browser } from '$app/environment';

/**
 * Update the browser URL to reflect the currently active chat
 * Uses SvelteKit's replaceState to avoid creating browser history entries (privacy-first)
 * 
 * NOTE: This function is no longer actively used for normal chat navigation.
 * URLs are only set temporarily for deep linking and are cleared immediately after loading.
 * Kept for backward compatibility and potential future use cases.
 * 
 * @param chatId - The chat ID to add to the URL, or null to clear
 */
export function updateChatUrl(chatId: string | null): void {
	if (!browser) return; // SSR safety
	
	try {
		const baseUrl = window.location.pathname + window.location.search;
		
		if (chatId) {
			// Add chat ID to URL using hash fragment (not sent to server)
			const newUrl = `${baseUrl}#chat-id=${chatId}`;
			
			// Use SvelteKit's replaceState to avoid creating browser history entry
			replaceState(newUrl, {});
			
			console.debug(`[ChatUrlService] Updated URL to: ${newUrl} (no history entry)`);
		} else {
			// Clear chat ID from URL
			replaceState(baseUrl, {});
			
			console.debug(`[ChatUrlService] Cleared chat ID from URL (no history entry)`);
		}
	} catch (error) {
		// Fail silently if URL update fails (e.g., in some sandboxed contexts)
		console.warn('[ChatUrlService] Failed to update URL:', error);
	}
}

/**
 * Extract chat ID from the current URL hash
 * Supports format: #chat-id={chatId}
 * 
 * @returns The chat ID if found in URL, null otherwise
 */
export function getChatIdFromUrl(): string | null {
	if (typeof window === 'undefined') return null; // SSR safety
	
	try {
		const hash = window.location.hash;
		
		// Check for #chat-id={chatId} format
		if (hash.startsWith('#chat-id=')) {
			const chatId = hash.substring(9); // Remove '#chat-id=' prefix
			if (chatId && chatId.length > 0) {
				console.debug(`[ChatUrlService] Found chat ID in URL: ${chatId}`);
				return chatId;
			}
		}
		
		return null;
	} catch (error) {
		console.warn('[ChatUrlService] Failed to extract chat ID from URL:', error);
		return null;
	}
}

/**
 * Clear the chat ID from the URL
 * Convenience function that calls updateChatUrl(null)
 */
export function clearChatUrl(): void {
	updateChatUrl(null);
}

/**
 * Check if a chat URL is currently set
 * 
 * @returns True if a chat ID is present in the URL
 */
export function hasChatUrl(): boolean {
	return getChatIdFromUrl() !== null;
}

