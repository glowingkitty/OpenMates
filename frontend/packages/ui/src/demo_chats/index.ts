import type { DemoChat } from './types';
import { welcomeChat } from './data/welcome';
import { whatMakesDifferentChat } from './data/what-makes-different';
import { LEGAL_CHATS } from '../legal';

// Export types
export type { DemoChat, DemoMessage } from './types';

// Export conversion utilities
export { convertDemoChatToChat, convertDemoMessagesToMessages, getDemoMessages, isDemoChat, isLegalChat, isPublicChat } from './convertToChat';
export { loadDemoChatsIntoDB, clearDemoChats } from './loadDemoChats';

// Export translation utilities (for i18n support)
export { translateDemoChat, translateDemoChats } from './translateDemoChat';

// Export legal chats for use in components
export { LEGAL_CHATS, getLegalChatBySlug, getLegalChatById } from '../legal';

/**
 * Demo chats shown in sidebar (excluding legal docs - they're accessed via dedicated routes)
 * 
 * IMPORTANT: ALL demo chats use translation keys from i18n/locales/{locale}.json
 * You MUST use translateDemoChat() or translateDemoChats() to resolve translations at runtime.
 */
export const DEMO_CHATS: DemoChat[] = [
	welcomeChat,
	whatMakesDifferentChat
	// Privacy, Terms, Imprint are NOT demo chats - they're accessed via /privacy, /terms, /imprint routes
	// More will be added: october-2025-updates, example-learn-something, developers, stay-up-to-date
	// Apps feature: example-power-of-apps (coming soon when Apps are implemented)
].sort((a, b) => a.metadata.order - b.metadata.order);

// Helper functions to find demo chats
export function getDemoChatBySlug(slug: string): DemoChat | undefined {
	return DEMO_CHATS.find(chat => chat.slug === slug);
}

export function getDemoChatById(id: string): DemoChat | undefined {
	return DEMO_CHATS.find(chat => chat.chat_id === id);
}

export function getFeaturedDemoChats(): DemoChat[] {
	return DEMO_CHATS.filter(chat => chat.metadata.featured);
}

/**
 * Get a public chat (demo or legal) by ID
 * Searches both DEMO_CHATS and LEGAL_CHATS
 */
export function getPublicChatById(id: string): DemoChat | undefined {
	return getDemoChatById(id) || LEGAL_CHATS.find(chat => chat.chat_id === id);
}

/**
 * Get all public chats (demo + legal) combined
 * Useful for loading messages from static bundle
 */
export function getAllPublicChats(): DemoChat[] {
	return [...DEMO_CHATS, ...LEGAL_CHATS];
}
