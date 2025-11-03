import type { DemoChat } from '../../demo_chats/types';

/**
 * Privacy Policy legal chat
 * 
 * Content is built from translation keys at runtime using buildPrivacyPolicyContent().
 * This ensures the chat content matches the Svelte component translations.
 * 
 * The translation keys are located in: frontend/packages/ui/src/i18n/locales/{locale}.json
 * under the 'legal.privacy.*' path.
 */
export const privacyPolicyChat: DemoChat = {
	chat_id: 'legal-privacy',
	slug: 'privacy',
	title: 'legal.privacy.title.text', // Translation key - resolved at runtime
	description: 'metadata.legal_privacy.description.text', // Translation key - resolved at runtime
	keywords: ['privacy', 'data protection', 'GDPR', 'encryption', 'security', 'zero-knowledge'],
	messages: [
		{
			id: 'privacy-1',
			role: 'assistant',
			// Content will be built from translation keys at runtime
			// See buildPrivacyPolicyContent() in buildLegalContent.ts
			content: '', // Placeholder - will be built from translation keys
			timestamp: '2025-01-01T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		// These can be translated if translation keys are added later
		"Can you really not read my messages?",
		"How does zero-knowledge encryption work?",
		"What if I lose my encryption key?",
		"Do AI providers see my messages?",
		"How do I delete my account?",
		"What data do you share with third parties?"
	],
	metadata: {
		category: 'openmates_official', // Official OpenMates category - shows favicon, not mate profile
		icon_names: ['shield-check', 'lock', 'eye-off'], // Security + encryption + privacy
		featured: false, // Don't show in regular sidebar (but always visible)
		order: 3, // Order: 1=welcome, 2=different, 3=privacy, 4=terms, 5=imprint
		lastUpdated: '2025-01-01T00:00:00Z'
	}
};

