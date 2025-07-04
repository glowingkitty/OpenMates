import type { Chat as ChatType } from '../../../types/chat';
import { get } from 'svelte/store';
import { locale as svelteLocaleStore } from 'svelte-i18n';

/**
 * Groups chats by time periods (e.g., "today", "yesterday", "previous_7_days").
 *
 * @param chatsToGroup An array of `ChatType` objects to be grouped.
 * @returns A record where keys are group identifiers (e.g., "today") and values are arrays of `ChatType` objects.
 */
export function groupChats(chatsToGroup: ChatType[]): Record<string, ChatType[]> {
    return chatsToGroup.reduce<Record<string, ChatType[]>>((groups, chat) => {
        const now = new Date();
        // Use last_edited_overall_timestamp for grouping, convert from Unix timestamp (seconds) to Date (milliseconds)
        // Fallback to updatedAt if last_edited_overall_timestamp is not available
        const chatDateSource = new Date(chat.last_edited_overall_timestamp * 1000);

        if (!chatDateSource || isNaN(chatDateSource.getTime())) {
            console.warn(`[ChatGroupUtils] Chat ${chat.chat_id} has invalid date for grouping. Placing in 'today'.`);
            const groupKey = 'today'; // Default group for invalid dates
            if (!groups[groupKey]) {
                groups[groupKey] = [];
            }
            groups[groupKey].push(chat);
            return groups;
        }
        
        // Clone dates to avoid modifying original date objects when setting hours
        const nowDateOnly = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const chatDateOnly = new Date(chatDateSource.getFullYear(), chatDateSource.getMonth(), chatDateSource.getDate());

        const diffTime = nowDateOnly.getTime() - chatDateOnly.getTime();
        const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));

        let groupKey: string;
        if (diffDays === 0) {
            groupKey = 'today';
        } else if (diffDays === 1) {
            groupKey = 'yesterday';
        } else if (diffDays < 7) {
            groupKey = 'previous_7_days';
        } else if (diffDays < 30) {
            groupKey = 'previous_30_days';
        } else {
            // Group by month for older chats, e.g., "month_2025_5" for May 2025
            groupKey = `month_${chatDateSource.getFullYear()}_${chatDateSource.getMonth() + 1}`;
        }

        if (!groups[groupKey]) {
            groups[groupKey] = [];
        }
        groups[groupKey].push(chat);
        return groups;
    }, {});
}

/**
 * Provides a localized title for a given group key.
 *
 * @param groupKey The key identifying the chat group (e.g., "today", "month_2025_5").
 * @param t The svelte-i18n translation function (`$_`).
 * @returns A localized string for the group title.
 */
export function getLocalizedGroupTitle(groupKey: string, t: (key: string, options?: any) => string): string {
    if (groupKey === 'today') return t('activity.today.text');
    if (groupKey === 'yesterday') return t('activity.yesterday.text');
    if (groupKey === 'previous_7_days') return t('activity.previous_7_days.text');
    if (groupKey === 'previous_30_days') return t('activity.previous_30_days.text');
    
    if (groupKey.startsWith('month_')) {
        const parts = groupKey.split('_');
        if (parts.length === 3) {
            const year = parseInt(parts[1], 10);
            const month = parseInt(parts[2], 10);
            if (!isNaN(year) && !isNaN(month)) {
                const date = new Date(year, month - 1);
                // Use current locale from svelte-i18n store for formatting
                const currentLocale = get(svelteLocaleStore);
                return date.toLocaleString(currentLocale || undefined, { month: 'long', year: 'numeric' });
            }
        }
    }
    // Fallback for unknown group keys or malformed month keys
    return groupKey; 
}