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
	title: 'legal.imprint.title', // Translation key - resolved at runtime
	description: 'metadata.legal_imprint.description', // Translation key - resolved at runtime
	keywords: ['imprint', 'impressum', 'legal notice', 'company', 'contact', 'legal'],
	messages: [
		{
			id: 'imprint-1',
			role: 'assistant',
			// Content will be built from translation keys at runtime
			// See buildImprintContent() in buildLegalContent.ts
			// Note: Full contact details are shown via SVG images in the Svelte component
			content: '', // Placeholder - will be built from translation keys
			timestamp: '2026-01-28T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		'legal.imprint.follow_up_1',
		'legal.imprint.follow_up_2',
		'legal.imprint.follow_up_3',
		'legal.imprint.follow_up_4',
		'legal.imprint.follow_up_5'
	],
	
	metadata: {
		category: 'openmates_official', // Official OpenMates category - shows favicon, not mate profile
		icon_names: ['building', 'map-pin', 'mail'],
		featured: false, // Don't show in regular sidebar (but always visible)
		order: 5, // Order: 1=welcome, 2=different, 3=privacy, 4=terms, 5=imprint
		lastUpdated: '2026-01-28T00:00:00Z' // Updated date kept for consistency, though imprint doesn't display it
	}
};

