import type { DemoChat } from '../../demo_chats/types';

/**
 * Imprint legal chat
 * 
 * Content is built from translation keys at runtime using buildImprintContent().
 * This ensures the chat content matches the Svelte component translations.
 * 
 * Note: The Svelte component uses SVG images for contact information, so the chat
 * version has simplified text. Full contact details are in the SVG images.
 * 
 * The translation keys are located in: frontend/packages/ui/src/i18n/locales/{locale}.json
 * under the 'legal.imprint.*' path.
 */
export const imprintChat: DemoChat = {
	chat_id: 'legal-imprint',
	slug: 'imprint',
	title: 'legal.imprint.title.text', // Translation key - resolved at runtime
	description: 'metadata.legal_imprint.description.text', // Translation key - resolved at runtime
	keywords: ['imprint', 'impressum', 'legal notice', 'company', 'contact', 'legal'],
	messages: [
		{
			id: 'imprint-1',
			role: 'assistant',
			// Content will be built from translation keys at runtime
			// See buildImprintContent() in buildLegalContent.ts
			// Note: Full contact details are shown via SVG images in the Svelte component
			content: '', // Placeholder - will be built from translation keys
			timestamp: '2025-01-01T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		// These can be translated if translation keys are added later
		"Why does German law require an Imprint?",
		"How can I contact your legal team?",
		"What open source licenses do you use?",
		"Where is your company registered?"
	],
	
	metadata: {
		category: 'openmates_official', // Official OpenMates category - shows favicon, not mate profile
		icon_names: ['building', 'map-pin', 'mail'],
		featured: false, // Don't show in regular sidebar (but always visible)
		order: 5, // Order: 1=welcome, 2=different, 3=privacy, 4=terms, 5=imprint
		lastUpdated: '2025-01-01T00:00:00Z'
	}
};

