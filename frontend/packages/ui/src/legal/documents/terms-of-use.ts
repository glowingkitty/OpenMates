import type { DemoChat } from '../../demo_chats/types';

/**
 * Terms of Use legal chat
 * 
 * Content is built from translation keys at runtime using buildTermsOfUseContent().
 * This ensures the chat content matches the Svelte component translations.
 * 
 * The translation keys are located in: frontend/packages/ui/src/i18n/locales/{locale}.json
 * under the 'legal.terms.*' path.
 */
export const termsOfUseChat: DemoChat = {
	chat_id: 'legal-terms',
	slug: 'terms',
	title: 'legal.terms.title.text', // Translation key - resolved at runtime
	description: 'metadata.legal_terms.description.text', // Translation key - resolved at runtime
	keywords: ['terms', 'conditions', 'usage', 'rules', 'agreement', 'legal'],
	messages: [
		{
			id: 'terms-1',
			role: 'assistant',
			// Content will be built from translation keys at runtime
			// See buildTermsOfUseContent() in buildLegalContent.ts
			content: '', // Placeholder - will be built from translation keys
			timestamp: '2025-01-01T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		'legal.terms.follow_up_1.text',
		'legal.terms.follow_up_2.text',
		'legal.terms.follow_up_3.text',
		'legal.terms.follow_up_4.text',
		'legal.terms.follow_up_5.text',
		'legal.terms.follow_up_6.text'
	],
	metadata: {
		category: 'openmates_official', // Official OpenMates category - shows favicon, not mate profile
		icon_names: ['file-text', 'scale', 'shield'],
		featured: false, // Don't show in regular sidebar (but always visible)
		order: 4, // Order: 1=welcome, 2=different, 3=privacy, 4=terms, 5=imprint
		lastUpdated: '2025-01-01T00:00:00Z'
	}
};
