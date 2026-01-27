import type { Chat, Message } from '../types/chat';
import type { DemoChat, DemoMessage } from './types';
import { translateDemoChat } from './translateDemoChat';
import { LEGAL_CHATS } from '../legal';
import { getCommunityDemoMessages, isCommunityDemo } from './communityDemoStore';

/**
 * Convert a demo chat to the Chat format used by the app
 * Demo chats are stored as CLEARTEXT in IndexedDB since they're public template content
 * (already decrypted by the server before being sent to the client)
 * 
 * ARCHITECTURE: Demo chats use cleartext field names (category, icon, follow_up_request_suggestions)
 * NOT encrypted_* field names, because the data is already decrypted server-side.
 * 
 * IMPORTANT: Demo chats use timestamps from 7 days ago to group them under "Last 7 days"
 * and maintain consistent order based on metadata.order (lower order = newer timestamp = shows first)
 */
export function convertDemoChatToChat(demoChat: DemoChat): Chat {
	// Use timestamps from 7 days ago, with lower order numbers getting newer timestamps
	// This ensures demo chats appear in the "Last 7 days" group and sort correctly
	const sevenDaysAgo = Date.now() - (7 * 24 * 60 * 60 * 1000); // 7 days in milliseconds
	const timestamp = sevenDaysAgo - (demoChat.metadata.order * 1000); // Subtract order (lower order = newer time)

	return {
		chat_id: demoChat.chat_id,
		title: demoChat.title, // Plaintext title for demo chats
		encrypted_title: null, // No encrypted title for demo chats
		// CLEARTEXT fields - demo chats are already decrypted server-side
		category: demoChat.metadata.category,
		icon: demoChat.metadata.icon_names.join(','),
		follow_up_request_suggestions: demoChat.follow_up_suggestions ? JSON.stringify(demoChat.follow_up_suggestions) : undefined,
		messages_v: 1,
		title_v: 1,
		last_edited_overall_timestamp: timestamp,
		unread_count: 0,
		created_at: timestamp,
		updated_at: timestamp
	};
}

/**
 * Convert demo messages to Message format
 * Demo messages are stored as CLEARTEXT in IndexedDB since they're public template content
 * (already decrypted by the server before being sent to the client)
 * 
 * ARCHITECTURE: Demo messages use cleartext field names (content, category)
 * NOT encrypted_* field names, because the data is already decrypted server-side.
 */
export function convertDemoMessagesToMessages(demoMessages: DemoMessage[], chatId: string, category: string): Message[] {
	return demoMessages.map(demoMsg => ({
		message_id: demoMsg.id,
		chat_id: chatId,
		role: demoMsg.role === 'user' ? 'user' as const : 'assistant' as const,
		// CLEARTEXT fields - demo messages are already decrypted server-side
		content: demoMsg.content,
		category: demoMsg.role === 'assistant' ? category : undefined,
		created_at: new Date(demoMsg.timestamp).getTime(),
		status: 'synced' as const // Demo messages are always synced
	}));
}

/**
 * Helper function to get messages for a public chat (demo or legal) by chat_id
 * Searches in order:
 * 1. Static demo chats (DEMO_CHATS array - in-memory)
 * 2. Legal chats (LEGAL_CHATS array - in-memory)
 * 3. Community demo chats (communityDemoStore - in-memory, fetched from server)
 * 
 * ARCHITECTURE: All demo/public chat data is stored in-memory, never in IndexedDB.
 * This avoids database initialization issues during logout/cleanup.
 * 
 * @param chatId - The chat ID to search for (e.g., 'demo-for-everyone', 'legal-privacy', 'demo-1')
 * @param demoChats - Array of static demo chats (from DEMO_CHATS)
 * @param legalChats - Array of legal chats (from LEGAL_CHATS) - optional, will import if not provided
 * @returns Array of messages for the chat, or empty array if not found
 */
export function getDemoMessages(chatId: string, demoChats: DemoChat[], legalChats?: DemoChat[]): Message[] {
	// 1. Search in static demo chats first (these are hardcoded in TypeScript)
	let foundChat = demoChats.find(chat => chat.chat_id === chatId);
	
	// 2. If not found, search in legal chats (use provided array or fallback to imported LEGAL_CHATS)
	if (!foundChat) {
		const legalChatsToSearch = legalChats || LEGAL_CHATS;
		foundChat = legalChatsToSearch.find(chat => chat.chat_id === chatId);
	}
	
	// 3. If still not found, check community demo store (fetched from server, stored in-memory)
	// Offline support is provided by proactive cache loading in loadDemoChatsFromServer
	if (!foundChat && (isCommunityDemo(chatId) || chatId.startsWith('demo-'))) {
		const communityMessages = getCommunityDemoMessages(chatId);
		if (communityMessages.length > 0) {
			console.debug(`[convertToChat] Found ${communityMessages.length} messages in community demo store for: ${chatId}`);
			return communityMessages;
		}

		// No messages in memory - this can happen if:
		// 1. Cache hasn't loaded yet (should be rare, loaded on app start)
		// 2. User is offline and cache was never populated
		// 3. Language reload is in progress (store was cleared)
		// In these cases, return empty array to avoid blocking the UI
		if (chatId.startsWith('demo-')) {
			console.debug(`[convertToChat] Community demo ${chatId} messages not found in memory (may be loading or reloading)`);
		}
		return [];
	}
	
	if (!foundChat) {
		// Only warn if this isn't a community demo (which might still be loading)
		if (!chatId.startsWith('demo-')) {
			console.warn(`[convertToChat] No public chat found for ID: ${chatId}`);
		}
		return [];
	}
	
	// Translate the chat to the user's locale before converting messages
	const translatedChat = translateDemoChat(foundChat);
	return convertDemoMessagesToMessages(translatedChat.messages, chatId, translatedChat.metadata.category);
}

/**
 * Check if a chat is a demo chat (starts with 'demo-' prefix)
 * Includes static demos (demo-for-everyone, demo-for-developers, etc.) and community demos (demo-1, demo-2, etc.)
 */
export function isDemoChat(chatId: string): boolean {
	return chatId.startsWith('demo-');
}

/**
 * Check if a chat is a legal chat (starts with 'legal-')
 */
export function isLegalChat(chatId: string): boolean {
	return chatId.startsWith('legal-');
}

/**
 * Check if a chat is a public chat (demo, community demo, or legal) - these are loaded from static bundle or as frozen snapshots
 * Both demo chats and legal chats use the same infrastructure for loading messages
 */
export function isPublicChat(chatId: string): boolean {
	return isDemoChat(chatId) || isLegalChat(chatId);
}
