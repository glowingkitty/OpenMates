/**
 * Legal Documents System
 * 
 * This module exports all legal documents (Privacy Policy, Terms of Use, Imprint)
 * that are accessible via dedicated routes and Settings menu.
 * 
 * These are special demo chats (featured: false) - they don't appear in the regular sidebar
 * but are loaded when accessed directly via URL or Settings.
 */

export { privacyPolicyChat } from './documents/privacy-policy';
export { termsOfUseChat } from './documents/terms-of-use';
export { imprintChat } from './documents/imprint';

import { privacyPolicyChat } from './documents/privacy-policy';
import { termsOfUseChat } from './documents/terms-of-use';
import { imprintChat } from './documents/imprint';
import type { DemoChat } from '../demo_chats/types';

/**
 * Array of all legal document chats, sorted by order
 */
export const LEGAL_CHATS: DemoChat[] = [
	privacyPolicyChat,
	termsOfUseChat,
	imprintChat
].sort((a, b) => a.metadata.order - b.metadata.order);

/**
 * Get a legal chat by its slug (e.g., 'privacy', 'terms', 'imprint')
 */
export function getLegalChatBySlug(slug: string): DemoChat | undefined {
	return LEGAL_CHATS.find(chat => chat.slug === slug);
}

/**
 * Get a legal chat by its chat_id (e.g., 'legal-privacy', 'legal-terms', 'legal-imprint')
 */
export function getLegalChatById(chatId: string): DemoChat | undefined {
	return LEGAL_CHATS.find(chat => chat.chat_id === chatId);
}

