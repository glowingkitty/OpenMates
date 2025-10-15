/**
 * Chat URL Service
 * 
 * Manages URL-based chat navigation with privacy-first approach.
 * 
 * Privacy Features:
 * - Uses history.replaceState() to update URL WITHOUT adding browser history entries
 * - This prevents chat navigation from appearing in browser history
 * - Hash fragments (#) are never sent to server, providing server-side privacy
 * - Combined approach: Private from both server AND browser history
 * 
 * Use Cases:
 * - Share direct links to specific chats
 * - Deep link to chats from external sources
 * - Restore last viewed chat on page reload
 */

/**
 * Update the browser URL to reflect the currently active chat
 * Uses replaceState to avoid creating browser history entries (privacy-first)
 * 
 * @param chatId - The chat ID to add to the URL, or null to clear
 */
export function updateChatUrl(chatId: string | null): void {
	if (typeof window === 'undefined') return; // SSR safety
	
	try {
		const baseUrl = window.location.pathname + window.location.search;
		
		if (chatId) {
			// Add chat ID to URL using hash fragment (not sent to server)
			const newUrl = `${baseUrl}#chat_id=${chatId}`;
			
			// Use replaceState to avoid creating browser history entry
			window.history.replaceState(
				{ chatId }, // State object for programmatic access
				'', // Title (unused by most browsers)
				newUrl
			);
			
			console.debug(`[ChatUrlService] Updated URL to: ${newUrl} (no history entry)`);
		} else {
			// Clear chat ID from URL
			window.history.replaceState(
				{}, // Empty state
				'',
				baseUrl
			);
			
			console.debug(`[ChatUrlService] Cleared chat ID from URL (no history entry)`);
		}
	} catch (error) {
		// Fail silently if URL update fails (e.g., in some sandboxed contexts)
		console.warn('[ChatUrlService] Failed to update URL:', error);
	}
}

/**
 * Extract chat ID from the current URL hash
 * Supports format: #chat_id={chatId}
 * 
 * @returns The chat ID if found in URL, null otherwise
 */
export function getChatIdFromUrl(): string | null {
	if (typeof window === 'undefined') return null; // SSR safety
	
	try {
		const hash = window.location.hash;
		
		// Check for #chat_id={chatId} format
		if (hash.startsWith('#chat_id=')) {
			const chatId = hash.substring(9); // Remove '#chat_id=' prefix
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

