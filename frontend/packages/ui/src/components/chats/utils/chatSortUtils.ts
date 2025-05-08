import type { Chat as ChatType } from '../../../types/chat';

/**
 * Sorts an array of chats based on multiple criteria.
 * - Primary sort: `last_edited_overall_timestamp` in descending order.
 * - Secondary sort: Server's preferred order (`currentServerSortOrder`) if timestamps are equal or undefined.
 * - Fallback sort: `updatedAt` timestamp in descending order if still tied.
 *
 * @param chatsToSort The array of `ChatType` objects to be sorted.
 * @param currentServerSortOrder An array of `chat_id` strings representing the server's preferred sort order.
 * @returns A new array containing the sorted `ChatType` objects.
 */
export function sortChats(chatsToSort: ChatType[], currentServerSortOrder: string[]): ChatType[] {
    // Create a shallow copy to avoid mutating the original array
    return [...chatsToSort].sort((a, b) => {
        // Primary sort: last_edited_overall_timestamp descending
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

        // Fallback to updatedAt if still tied (e.g., for purely local items not yet in server order)
        // Ensure Date objects are valid before calling getTime()
        const aUpdated = a.updatedAt instanceof Date ? a.updatedAt.getTime() : 0;
        const bUpdated = b.updatedAt instanceof Date ? b.updatedAt.getTime() : 0;
        return bUpdated - aUpdated; // Sort by most recent updatedAt descending
    });
}