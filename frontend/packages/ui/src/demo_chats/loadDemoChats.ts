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

		// Load community demo chats from server
		try {
			const { getApiEndpoint } = await import('@repo/ui');
			const lang = document.documentElement.lang || 'en';
			const response = await fetch(getApiEndpoint(`/v1/demo/chats?lang=${lang}`));
			if (response.ok) {
				const data = await response.json();
				const communityDemos = data.demo_chats || [];
				for (const demo of communityDemos) {
					// Fetch full data for each community demo
					const detailResponse = await fetch(getApiEndpoint(`/v1/demo/chat/${demo.demo_id}?lang=${lang}`));
					if (detailResponse.ok) {
						const detailData = await detailResponse.json();
						const chatData = detailData.chat_data;
						
						// Convert to standard Chat object
						const chat: import('../types/chat').Chat = {
							chat_id: demo.demo_id,
							title: detailData.title,
							encrypted_title: null,
							messages_v: chatData.messages.length,
							title_v: 1,
							draft_v: 0,
							created_at: Math.floor(new Date(demo.created_at).getTime() / 1000),
							updated_at: Math.floor(new Date(demo.created_at).getTime() / 1000),
							last_edited_overall_timestamp: Math.floor(new Date(demo.created_at).getTime() / 1000),
							unread_count: 0,
							pinned: false
						};
						
						await chatDB.addChat(chat);
						
						// Store messages (already cleartext from server)
						for (const msg of chatData.messages) {
							await chatDB.saveMessage({
								message_id: msg.message_id,
								chat_id: chat.chat_id,
								role: msg.role,
								content: msg.content,
								created_at: msg.created_at,
								status: 'synced',
								encrypted_content: '' // DB skips encryption for demo IDs
							});
						}
						
						// Store embeds
						for (const emb of chatData.embeds) {
							// TODO: Implement demo embed storage if needed
						}
						
						console.debug(`[loadDemoChats] Loaded community demo: ${detailData.title}`);
					}
				}
			}
		} catch (commError) {
			console.warn('[loadDemoChats] Failed to load community demos:', commError);
		}

		console.debug(`[loadDemoChats] Loaded ${DEMO_CHATS.length} static demo chats into IndexedDB`);
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
