import type { Chat as ChatType } from '../../../types/chat';

/**
 * Checks if a chat has a non-empty draft.
 * A draft is considered non-empty if encrypted_draft_md exists, is not null, and is not an empty string.
 * 
 * @param chat The chat to check
 * @returns true if the chat has a non-empty draft, false otherwise
 */
function hasNonEmptyDraft(chat: ChatType): boolean {
    return !!(
        chat.encrypted_draft_md && 
        chat.encrypted_draft_md !== null && 
        chat.encrypted_draft_md.length > 0
    );
}

/**
 * Sorts an array of chats based on multiple criteria.
 * - Primary sort: Pinned chats appear first (sorted by their own criteria)
 * - Secondary sort: Chats with non-empty drafts appear next (among themselves, sorted by last_edited_overall_timestamp)
 * - Tertiary sort: Regular chats without drafts, sorted by `last_edited_overall_timestamp` in descending order
 * - Fallback sort: Server's preferred order (`currentServerSortOrder`) if timestamps are equal or undefined
 * - Final fallback: `updatedAt` timestamp in descending order if still tied
 *
 * CRITICAL: Only messages update `last_edited_overall_timestamp`. Drafts do NOT update this timestamp,
 * ensuring old chats don't appear as recent just because they have drafts.
 *
 * @param chatsToSort The array of `ChatType` objects to be sorted.
 * @param currentServerSortOrder An array of `chat_id` strings representing the server's preferred sort order.
 * @returns A new array containing the sorted `ChatType` objects.
 */
export function sortChats(chatsToSort: ChatType[], currentServerSortOrder: string[]): ChatType[] {
    // Create a shallow copy to avoid mutating the original array
    return [...chatsToSort].sort((a, b) => {
        // Check if chats are pinned
        const aPinned = a.pinned || false;
        const bPinned = b.pinned || false;

        // Primary sort: Pinned chats come before non-pinned chats
        if (aPinned && !bPinned) {
            return -1; // a (pinned) comes first
        }
        if (!aPinned && bPinned) {
            return 1; // b (pinned) comes first
        }

        // Both pinned or both not pinned - check drafts within their category
        // Check if chats have non-empty drafts
        const aHasDraft = hasNonEmptyDraft(a);
        const bHasDraft = hasNonEmptyDraft(b);

        // Secondary sort: Chats with non-empty drafts appear before chats without drafts (within pinned/unpinned category)
        if (aHasDraft && !bHasDraft) {
            return -1; // a (with draft) comes first
        }
        if (!aHasDraft && bHasDraft) {
            return 1; // b (with draft) comes first
        }
        
        // Both have drafts or both don't have drafts - sort by last_edited_overall_timestamp
        // This ensures chats with drafts are sorted among themselves by last message time
        // and chats without drafts are sorted by last message time
        // Fallback to 0 if timestamp is null or undefined to ensure consistent comparison
        const timeDiff = (b.last_edited_overall_timestamp || 0) - (a.last_edited_overall_timestamp || 0);
        if (timeDiff !== 0) {
            return timeDiff;
        }

        // Secondary sort: server's preferred order if timestamps are equal or not definitive
        const indexA = currentServerSortOrder.indexOf(a.chat_id);
        const indexB = currentServerSortOrder.indexOf(b.chat_id);

        if (indexA !== -1 && indexB !== -1) {
            return indexA - indexB; // Sort by lower index first
        }
        // If only one chat is in the server order, prioritize it
        if (indexA !== -1) {
            return -1; // a comes first
        }
        if (indexB !== -1) {
            return 1;  // b comes first
        }

        // Fallback to updated_at if still tied (e.g., for purely local items not yet in server order)
        // Use timestamp (number) instead of Date object
        const aUpdated = a.updated_at || 0;
        const bUpdated = b.updated_at || 0;
        return bUpdated - aUpdated; // Sort by most recent updated_at descending
    });
}