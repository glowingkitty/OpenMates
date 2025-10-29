import type { DemoChat } from './types';
import { welcomeChat } from './data/welcome';
import { whatMakesDifferentChat } from './data/what-makes-different';
import { powerOfAppsChat } from './data/example-power-of-apps';

// Export types
export type { DemoChat, DemoMessage } from './types';

// Export conversion utilities
export { convertDemoChatToChat, convertDemoMessagesToMessages, getDemoMessages, isDemoChat } from './convertToChat';
export { loadDemoChatsIntoDB, clearDemoChats } from './loadDemoChats';

// Demo chats shown in sidebar (excluding legal docs - they're accessed via dedicated routes)
export const DEMO_CHATS: DemoChat[] = [
	welcomeChat,
	whatMakesDifferentChat,
	powerOfAppsChat
	// Privacy, Terms, Imprint are NOT demo chats - they're accessed via /privacy, /terms, /imprint routes
	// More will be added: october-2025-updates, example-learn-something, developers, stay-up-to-date
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
