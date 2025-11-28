import { chatDB } from '../services/db';
import { DEMO_CHATS } from './index';
import { convertDemoChatToChat, convertDemoMessagesToMessages } from './convertToChat';

/**
 * Load demo chats into IndexedDB for non-authenticated users
 * This allows the existing chat components to work with demo chats seamlessly
 * 
 * Demo chats are stored as PLAINTEXT (not encrypted) since they're public template content.
 * The database layer automatically detects demo chats (chat_id starting with 'demo-')
 * and skips all encryption/decryption operations.
 */
export async function loadDemoChatsIntoDB(): Promise<void> {
	try {
		await chatDB.init();

		// Convert and store each demo chat
		for (const demoChat of DEMO_CHATS) {
			const chat = convertDemoChatToChat(demoChat);
			const messages = convertDemoMessagesToMessages(demoChat.messages, demoChat.chat_id, demoChat.metadata.category);

			// Store chat - database will detect demo chat and skip encryption
			await chatDB.addChat(chat);

			// Store messages - database will detect demo chat messages and skip encryption
			for (const message of messages) {
				await chatDB.saveMessage({
					...message,
					chat_id: chat.chat_id
				});
			}

			console.debug(`[loadDemoChats] Loaded demo chat: ${demoChat.title}`);
		}

		console.debug(`[loadDemoChats] Loaded ${DEMO_CHATS.length} demo chats into IndexedDB`);
	} catch (error) {
		console.error('[loadDemoChats] Failed to load demo chats:', error);
	}
}

/**
 * Clear demo chats from IndexedDB
 */
export async function clearDemoChats(): Promise<void> {
	try {
		await chatDB.init();

		for (const demoChat of DEMO_CHATS) {
			await chatDB.deleteChat(demoChat.chat_id);
		}

		console.debug('[clearDemoChats] Cleared all demo chats from IndexedDB');
	} catch (error) {
		console.error('[clearDemoChats] Failed to clear demo chats:', error);
	}
}
