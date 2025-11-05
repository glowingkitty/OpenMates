import type { DemoChat } from '../types';

/**
 * Welcome demo chat - Translation keys from i18n/locales/{locale}.json
 * All content is translated at runtime using translateDemoChat()
 */
export const welcomeChat: DemoChat = {
	chat_id: 'demo-welcome',
	slug: 'welcome',
	title: 'demo_chats.welcome.title.text',
	description: 'demo_chats.welcome.description.text',
	keywords: ['AI assistant', 'getting started', 'introduction', 'OpenMates features'],
	messages: [
		{
			id: 'welcome-1',
			role: 'assistant',
			content: 'demo_chats.welcome.message.text',
			timestamp: new Date().toISOString()
		}
	],
	follow_up_suggestions: [
		'demo_chats.welcome.follow_up_1.text',
		'demo_chats.welcome.follow_up_2.text',
		'demo_chats.welcome.follow_up_3.text'
	],
	metadata: {
		category: 'general_knowledge', // Real category from mates.yml
		icon_names: ['hand-wave', 'rocket', 'sparkles'], // Lucide icons for welcome/introduction
		featured: true,
		order: 1,
		lastUpdated: new Date().toISOString()
	}
};
