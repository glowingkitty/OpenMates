/**
 * Chat URL Service
 *
 * Manages URL-based chat navigation with privacy-first approach.
 *
 * Public chats (intro, example, announcement, tips, legal) get semantic paths
 * (e.g. /intro/for-everyone, /announcements/introducing-openmates-v09) so that
 * shared links show proper OG previews — those paths have SSR SEO pages.
 *
 * Private chats still use the hash fragment (#chat-id=xxx) which is never sent
 * to the server, preserving server-side privacy.
 */

import { replaceState } from '$app/navigation';
import { browser } from '$app/environment';
import { getExampleChatData } from '../demo_chats/exampleChatStore';
import { getNewsletterChatById } from '../demo_chats/newsletterChatStore';

// Path prefixes that correspond to public-chat SEO routes.
// Used to detect when the URL should be reverted to / on navigation away.
export const SEMANTIC_CHAT_PATH_PREFIXES = [
	'/intro/',
	'/example/',
	'/announcements/',
	'/tips/',
	'/legal/'
] as const;

/**
 * Returns true when the current browser path is a public-chat semantic path
 * (i.e. one that should revert to / when the user navigates to a private chat).
 */
export function isOnSemanticChatPath(): boolean {
	if (typeof window === 'undefined') return false;
	const path = window.location.pathname;
	return SEMANTIC_CHAT_PATH_PREFIXES.some((prefix) => path.startsWith(prefix));
}

/**
 * Map a chat ID to its shareable semantic URL path.
 * Returns null for private chats (they stay on the hash).
 *
 * Mappings:
 *   demo-*          → /intro/{slug}
 *   example-*       → /example/{slug}   (slug from ExampleChat.slug)
 *   announcements-* → /announcements/{slug}
 *   tips-*          → /tips/{slug}
 *   legal-*         → /legal/{slug}
 */
export function getSemanticUrlForChat(chatId: string): string | null {
	if (chatId.startsWith('demo-')) {
		return `/intro/${chatId.slice('demo-'.length)}`;
	}
	if (chatId.startsWith('example-')) {
		const data = getExampleChatData(chatId);
		return data ? `/example/${data.slug}` : null;
	}
	if (chatId.startsWith('announcements-')) {
		const chat = getNewsletterChatById(chatId);
		return chat ? `/announcements/${chat.slug}` : null;
	}
	if (chatId.startsWith('tips-')) {
		const chat = getNewsletterChatById(chatId);
		return chat ? `/tips/${chat.slug}` : null;
	}
	if (chatId.startsWith('legal-')) {
		return `/legal/${chatId.slice('legal-'.length)}`;
	}
	return null;
}

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


