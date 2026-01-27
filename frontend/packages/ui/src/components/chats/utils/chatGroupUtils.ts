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
        // If chat has a predefined group key (e.g., 'intro', 'examples', 'legal'), use it directly
        // This allows manual overrides of the automatic time-based grouping
        if (chat.group_key) {
            const groupKey = chat.group_key;
            if (!groups[groupKey]) {
                groups[groupKey] = [];
            }
            groups[groupKey].push(chat);
            return groups;
        }

        const now = new Date();
        
        // CRITICAL FIX: Handle timestamp format mismatch between demo chats and real chats
        // Demo chats use milliseconds (from Date.now()), real chats use seconds (from Math.floor(Date.now() / 1000))
        // Detection: Timestamps in seconds are < 10000000000 (10-11 digits), timestamps in milliseconds are >= 1000000000000 (13+ digits)
        // Threshold: 10000000000 (Nov 2001 in seconds) - anything below is seconds, anything above is milliseconds
        let chatTimestamp = chat.last_edited_overall_timestamp;
        if (!chatTimestamp || chatTimestamp === 0) {
            // Invalid or zero timestamp - use current time as fallback (in seconds, then convert to milliseconds)
            console.warn(`[ChatGroupUtils] Chat ${chat.chat_id} has invalid/zero timestamp (${chatTimestamp}), using current time for grouping`);
            chatTimestamp = Date.now(); // Use milliseconds format for Date constructor
        } else if (chatTimestamp < 10000000000) {
            // Timestamp is in seconds (for real chats) - multiply by 1000 to convert to milliseconds
            chatTimestamp = chatTimestamp * 1000;
        }
        // If chatTimestamp >= 10000000000, it's already in milliseconds (demo chats) - use as-is
        
        const chatDateSource = new Date(chatTimestamp);

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
export function getLocalizedGroupTitle(groupKey: string, t: (key: string, options?: Record<string, unknown>) => string): string {
    if (groupKey === 'intro') return t('activity.intro.text');
    if (groupKey === 'examples') return t('activity.examples.text');
    if (groupKey === 'legal') return t('activity.legal.text');
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