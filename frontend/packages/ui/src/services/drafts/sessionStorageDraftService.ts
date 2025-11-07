// frontend/packages/ui/src/services/drafts/sessionStorageDraftService.ts
// Service for managing drafts in sessionStorage for non-authenticated users
// These drafts are stored as cleartext (no encryption) and are migrated to IndexedDB after login/signup

import { tipTapToCanonicalMarkdown } from '../../message_parsing/serializers';
import { parse_message } from '../../message_parsing/parse_message';
import type { TiptapJSON } from '../../types/chat';

/**
 * SessionStorage key prefix for drafts
 */
const DRAFT_KEY_PREFIX = 'draft_';

/**
 * SessionStorage key for storing all draft chat IDs (for easy enumeration)
 */
const DRAFT_IDS_KEY = 'draft_chat_ids';

/**
 * Interface for sessionStorage draft data
 */
interface SessionStorageDraft {
	markdown: string; // Cleartext markdown content
	preview: string | null; // Preview text for chat list display
	tiptapJSON: TiptapJSON; // TipTap JSON content for editor
	timestamp: number; // Timestamp when draft was last saved
}

/**
 * Get the sessionStorage key for a draft
 */
function getDraftKey(chatId: string): string {
	return `${DRAFT_KEY_PREFIX}${chatId}`;
}

/**
 * Get all draft chat IDs from sessionStorage
 */
function getAllDraftChatIds(): string[] {
	try {
		const idsJson = sessionStorage.getItem(DRAFT_IDS_KEY);
		if (!idsJson) return [];
		return JSON.parse(idsJson) as string[];
	} catch (error) {
		console.error('[SessionStorageDraftService] Error reading draft IDs:', error);
		return [];
	}
}

/**
 * Save a draft chat ID to the list
 */
function saveDraftChatId(chatId: string): void {
	try {
		const ids = getAllDraftChatIds();
		if (!ids.includes(chatId)) {
			ids.push(chatId);
			sessionStorage.setItem(DRAFT_IDS_KEY, JSON.stringify(ids));
		}
	} catch (error) {
		console.error('[SessionStorageDraftService] Error saving draft ID:', error);
	}
}

/**
 * Remove a draft chat ID from the list
 */
function removeDraftChatId(chatId: string): void {
	try {
		const ids = getAllDraftChatIds();
		const filtered = ids.filter(id => id !== chatId);
		sessionStorage.setItem(DRAFT_IDS_KEY, JSON.stringify(filtered));
	} catch (error) {
		console.error('[SessionStorageDraftService] Error removing draft ID:', error);
	}
}

/**
 * Save a draft to sessionStorage for a non-authenticated user
 * @param chatId The chat ID (can be demo chat ID or new chat ID)
 * @param tiptapJSON The TipTap JSON content from the editor
 * @param preview Optional preview text for chat list display
 */
export function saveSessionStorageDraft(
	chatId: string,
	tiptapJSON: TiptapJSON,
	preview: string | null = null
): void {
	try {
		// Convert TipTap JSON to markdown for storage
		const markdown = tipTapToCanonicalMarkdown(tiptapJSON);
		
		const draft: SessionStorageDraft = {
			markdown,
			preview,
			tiptapJSON,
			timestamp: Date.now()
		};
		
		const key = getDraftKey(chatId);
		sessionStorage.setItem(key, JSON.stringify(draft));
		saveDraftChatId(chatId);
		
		console.debug('[SessionStorageDraftService] Saved draft to sessionStorage:', {
			chatId,
			markdownLength: markdown.length,
			hasPreview: !!preview
		});
	} catch (error) {
		console.error('[SessionStorageDraftService] Error saving draft to sessionStorage:', error);
	}
}

/**
 * Load a draft from sessionStorage
 * @param chatId The chat ID to load the draft for
 * @returns The TipTap JSON content or null if no draft exists
 */
export function loadSessionStorageDraft(chatId: string): TiptapJSON | null {
	try {
		const key = getDraftKey(chatId);
		const draftJson = sessionStorage.getItem(key);
		if (!draftJson) return null;
		
		const draft: SessionStorageDraft = JSON.parse(draftJson);
		
		console.debug('[SessionStorageDraftService] Loaded draft from sessionStorage:', {
			chatId,
			markdownLength: draft.markdown.length,
			timestamp: draft.timestamp
		});
		
		return draft.tiptapJSON;
	} catch (error) {
		console.error('[SessionStorageDraftService] Error loading draft from sessionStorage:', error);
		return null;
	}
}

/**
 * Get draft preview text from sessionStorage
 * @param chatId The chat ID to get the preview for
 * @returns The preview text or null if no draft exists
 */
export function getSessionStorageDraftPreview(chatId: string): string | null {
	try {
		const key = getDraftKey(chatId);
		const draftJson = sessionStorage.getItem(key);
		if (!draftJson) return null;
		
		const draft: SessionStorageDraft = JSON.parse(draftJson);
		return draft.preview;
	} catch (error) {
		console.error('[SessionStorageDraftService] Error getting draft preview:', error);
		return null;
	}
}

/**
 * Delete a draft from sessionStorage
 * @param chatId The chat ID to delete the draft for
 */
export function deleteSessionStorageDraft(chatId: string): void {
	try {
		const key = getDraftKey(chatId);
		sessionStorage.removeItem(key);
		removeDraftChatId(chatId);
		
		console.debug('[SessionStorageDraftService] Deleted draft from sessionStorage:', chatId);
	} catch (error) {
		console.error('[SessionStorageDraftService] Error deleting draft from sessionStorage:', error);
	}
}

/**
 * Clear all drafts from sessionStorage
 * Called when user clicks "Demo" button to return to demo mode
 */
export function clearAllSessionStorageDrafts(): void {
	try {
		const ids = getAllDraftChatIds();
		
		// Remove all draft entries
		for (const chatId of ids) {
			const key = getDraftKey(chatId);
			sessionStorage.removeItem(key);
		}
		
		// Clear the IDs list
		sessionStorage.removeItem(DRAFT_IDS_KEY);
		
		console.debug('[SessionStorageDraftService] Cleared all drafts from sessionStorage:', ids.length);
	} catch (error) {
		console.error('[SessionStorageDraftService] Error clearing all drafts:', error);
	}
}

/**
 * Get all draft chat IDs that have drafts in sessionStorage
 * @returns Array of chat IDs with drafts
 */
export function getAllDraftChatIdsWithDrafts(): string[] {
	return getAllDraftChatIds();
}

/**
 * Migrate all sessionStorage drafts to IndexedDB after login/signup
 * This function should be called after successful authentication
 * @param chatDB The chat database instance
 * @param encryptWithMasterKey Function to encrypt content with master key
 */
export async function migrateSessionStorageDraftsToIndexedDB(
	chatDB: any,
	encryptWithMasterKey: (content: string) => Promise<string | null>
): Promise<void> {
	try {
		const ids = getAllDraftChatIds();
		
		if (ids.length === 0) {
			console.debug('[SessionStorageDraftService] No drafts to migrate');
			return;
		}
		
		console.info(`[SessionStorageDraftService] Migrating ${ids.length} drafts from sessionStorage to IndexedDB`);
		
		for (const chatId of ids) {
			try {
				const key = getDraftKey(chatId);
				const draftJson = sessionStorage.getItem(key);
				if (!draftJson) continue;
				
				const draft: SessionStorageDraft = JSON.parse(draftJson);
				
				// Encrypt the markdown and preview
				const encryptedMarkdown = await encryptWithMasterKey(draft.markdown);
				const encryptedPreview = draft.preview ? await encryptWithMasterKey(draft.preview) : null;
				
				if (!encryptedMarkdown) {
					console.warn(`[SessionStorageDraftService] Failed to encrypt draft for ${chatId}, skipping`);
					continue;
				}
				
				// Check if chat exists in IndexedDB
				let chat = await chatDB.getChat(chatId);
				
				if (!chat) {
					// Create new chat with draft
					chat = await chatDB.createNewChatWithCurrentUserDraft(encryptedMarkdown, encryptedPreview);
					console.info(`[SessionStorageDraftService] Created new chat ${chat.chat_id} with migrated draft`);
				} else {
					// Update existing chat with draft
					chat = await chatDB.saveCurrentUserChatDraft(chatId, encryptedMarkdown, encryptedPreview);
					console.info(`[SessionStorageDraftService] Updated chat ${chatId} with migrated draft`);
				}
				
				// Remove from sessionStorage after successful migration
				sessionStorage.removeItem(key);
				removeDraftChatId(chatId);
				
				console.debug(`[SessionStorageDraftService] Successfully migrated draft for ${chatId}`);
			} catch (error) {
				console.error(`[SessionStorageDraftService] Error migrating draft for ${chatId}:`, error);
				// Continue with other drafts even if one fails
			}
		}
		
		// Clear the IDs list after migration
		sessionStorage.removeItem(DRAFT_IDS_KEY);
		
		console.info('[SessionStorageDraftService] Draft migration completed');
	} catch (error) {
		console.error('[SessionStorageDraftService] Error during draft migration:', error);
	}
}

