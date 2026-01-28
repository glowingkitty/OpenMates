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
			timestamp: '2026-01-28T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		'legal.privacy.follow_up_1.text',
		'legal.privacy.follow_up_2.text',
		'legal.privacy.follow_up_3.text',
		'legal.privacy.follow_up_4.text',
		'legal.privacy.follow_up_5.text',
		'legal.privacy.follow_up_6.text'
	],
	metadata: {
		category: 'openmates_official', // Official OpenMates category - shows favicon, not mate profile
		icon_names: ['shield-check', 'lock', 'eye-off'], // Security + encryption + privacy
		featured: false, // Don't show in regular sidebar (but always visible)
		order: 3, // Order: 1=welcome, 2=different, 3=privacy, 4=terms, 5=imprint
		lastUpdated: '2026-01-28T00:00:00Z' // Single source of truth for "last updated" date - formatted via Intl.DateTimeFormat
	}
};

