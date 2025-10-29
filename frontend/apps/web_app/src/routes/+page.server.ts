import type { PageServerLoad } from './$types';
import { DEMO_CHATS } from '@repo/ui';

/**
 * Server-side load function for the main page
 * Pre-renders the Welcome demo chat for SEO and web crawlers
 */
export const load: PageServerLoad = async ({ setHeaders }) => {
	// Find the Welcome demo chat
	const welcomeChat = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
	
	if (!welcomeChat) {
		console.error('[+page.server] Welcome demo chat not found!');
		return {
			welcomeChat: null,
			seo: {
				title: 'OpenMates - Your AI Team',
				description: 'AI-powered assistant with end-to-end encryption and zero-knowledge architecture',
				keywords: []
			}
		};
	}

	// Set cache headers for better SEO
	setHeaders({
		'cache-control': 'public, max-age=3600' // Cache for 1 hour
	});

	// Return the welcome chat data for SSR with SEO metadata
	// This will be pre-rendered in the HTML, making it visible to crawlers
	return {
		welcomeChat: {
			id: welcomeChat.chat_id,
			title: welcomeChat.title,
			description: welcomeChat.description,
			keywords: welcomeChat.keywords,
			messages: welcomeChat.messages,
			category: welcomeChat.metadata.category
		},
		seo: {
			title: `OpenMates`,
			description: welcomeChat.description,
			keywords: welcomeChat.keywords
		}
	};
};

