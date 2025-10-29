import type { Chat, Message } from '../types/chat';
import type { DemoChat, DemoMessage } from './types';

/**
 * Convert a demo chat to the Chat format used by the app
 * Demo chats are stored as plaintext (not encrypted) since they're public template content
 * We add a plaintext `title` field so Chat.svelte can display it without decryption
 * Category and icon are stored in encrypted_* fields (as plaintext for demos) so the UI can access them
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
		title: demoChat.title, // Plaintext title for demo chats (not encrypted)
		encrypted_title: null, // No encrypted title for demo chats
		encrypted_category: demoChat.metadata.category, // Store category as plaintext (not actually encrypted for demos)
		encrypted_icon: demoChat.metadata.icon_names.join(','), // Store icon_names as comma-separated string (plaintext for demos)
		// Add follow-up suggestions as encrypted field (but store as plaintext JSON for demos)
		encrypted_follow_up_request_suggestions: demoChat.follow_up_suggestions ? JSON.stringify(demoChat.follow_up_suggestions) : undefined,
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
 * Demo messages are stored as plaintext (not encrypted) since they're public template content
 * We store the content in both encrypted_content (as plaintext) and content fields
 * Category is added to assistant messages based on metadata (stored as plaintext for demos)
 */
export function convertDemoMessagesToMessages(demoMessages: DemoMessage[], chatId: string, category: string): Message[] {
	return demoMessages.map(demoMsg => ({
		message_id: demoMsg.id,
		chat_id: chatId, // Set the chat_id for the messages
		role: demoMsg.role === 'user' ? 'user' as const : 'assistant' as const,
		encrypted_content: demoMsg.content, // Store as plaintext (not actually encrypted for demos)
		content: demoMsg.content, // Also set decrypted content for immediate display
		encrypted_category: demoMsg.role === 'assistant' ? category : undefined, // Add category for assistant messages (as plaintext)
		category: demoMsg.role === 'assistant' ? category : undefined, // Also set decrypted category for immediate display
		created_at: new Date(demoMsg.timestamp).getTime(),
		status: 'synced' as const // Demo messages are always synced
	}));
}

/**
 * Helper function to get messages for a demo chat by chat_id
 */
export function getDemoMessages(chatId: string, demoChats: DemoChat[]): Message[] {
	const demoChat = demoChats.find(chat => chat.chat_id === chatId);
	if (!demoChat) {
		console.warn(`[convertToChat] No demo chat found for ID: ${chatId}`);
		return [];
	}
	return convertDemoMessagesToMessages(demoChat.messages, chatId, demoChat.metadata.category);
}

/**
 * Check if a chat is a demo chat
 */
export function isDemoChat(chatId: string): boolean {
	return chatId.startsWith('demo-');
}
