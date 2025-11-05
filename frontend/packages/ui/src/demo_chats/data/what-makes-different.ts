import type { DemoChat } from '../types';

/**
 * "What makes OpenMates different?" demo chat - Translation keys from i18n/locales/{locale}.json
 * All content is translated at runtime using translateDemoChat()
 */
export const whatMakesDifferentChat: DemoChat = {
	chat_id: 'demo-different',
	slug: 'what-makes-different',
	title: 'demo_chats.what_makes_different.title.text',
	description: 'demo_chats.what_makes_different.description.text',
	keywords: ['features', 'privacy', 'mates', 'drafts', 'comparison', 'encryption'],
	messages: [
		{
			id: 'diff-1',
			role: 'user',
			content: 'demo_chats.what_makes_different.user_question.text',
			timestamp: new Date().toISOString()
		},
		{
			id: 'diff-2',
			role: 'assistant',
			content: 'demo_chats.what_makes_different.answer.text',
			timestamp: new Date().toISOString()
		}
	],
	follow_up_suggestions: [
		'demo_chats.what_makes_different.follow_up_1.text',
		'demo_chats.what_makes_different.follow_up_2.text',
		'demo_chats.what_makes_different.follow_up_3.text'
	],
	metadata: {
		category: 'general_knowledge', // Real category from mates.yml
		icon_names: ['shield-check', 'users', 'zap'], // Lucide icons for security/team/performance
		featured: true,
		order: 2,
		lastUpdated: new Date().toISOString()
	}
};
