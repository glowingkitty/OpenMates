/**
 * Chat settings context store.
 *
 * Holds the active chat settings payload in memory while the Settings shell is
 * open. Chat IDs and decrypted message metadata stay out of normal Settings
 * navigation and are not persisted into a public route list.
 */

import { writable } from 'svelte/store';
import type { Chat, Message } from '../types/chat';

export type ChatSettingsTab = 'plan' | 'tasks' | 'files' | 'usage' | 'share';

export interface ChatSettingsContext {
    chat: Chat;
    messages: Message[];
    activeTab: ChatSettingsTab;
}

export const CHAT_SETTINGS_ROUTE_PREFIX = 'chats';

const CHAT_SETTINGS_TABS: ChatSettingsTab[] = ['plan', 'tasks', 'files', 'usage', 'share'];

export function normalizeChatSettingsTab(tab: string | null | undefined): ChatSettingsTab {
    return CHAT_SETTINGS_TABS.includes(tab as ChatSettingsTab) ? (tab as ChatSettingsTab) : 'plan';
}

function createChatSettingsStore() {
    const { subscribe, set, update } = writable<ChatSettingsContext | null>(null);

    return {
        subscribe,
        open(chat: Chat, messages: Message[], activeTab: string | null | undefined = 'plan') {
            set({ chat, messages, activeTab: normalizeChatSettingsTab(activeTab) });
        },
        setTab(activeTab: string | null | undefined) {
            update((context) => context ? { ...context, activeTab: normalizeChatSettingsTab(activeTab) } : context);
        },
        clear() {
            set(null);
        },
    };
}

export const chatSettingsStore = createChatSettingsStore();

export function chatSettingsRouteFor(chatId: string, tab?: string | null): string {
    const normalizedTab = tab ? normalizeChatSettingsTab(tab) : null;
    return normalizedTab ? `${CHAT_SETTINGS_ROUTE_PREFIX}/${chatId}/${normalizedTab}` : `${CHAT_SETTINGS_ROUTE_PREFIX}/${chatId}`;
}
