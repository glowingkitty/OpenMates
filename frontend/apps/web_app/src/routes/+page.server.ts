import type { PageServerLoad } from './$types';
import { DEMO_CHATS } from '@repo/ui';
import { locale, waitLocale, _ } from 'svelte-i18n';
import { get } from 'svelte/store';

/**
 * Server-side load function for the main page
 * Pre-renders the Welcome demo chat for SEO and web crawlers with proper translations
 */
export const load: PageServerLoad = async ({ setHeaders, request, cookies, url }) => {
	// Detect user's preferred language from multiple sources (priority order):
	// 1. URL query parameter (?lang=de)
	// 2. Cookie (preferredLanguage)
	// 3. Accept-Language header
	// 4. Default to English
	
	const supportedLocales = ['en', 'de', 'es', 'fr', 'zh', 'ja'];
	
	const urlLangParam = url.searchParams.get('lang');
	const savedLocale = cookies.get('preferredLanguage');
	const acceptLanguage = request.headers.get('accept-language');
	const browserLocale = acceptLanguage?.split(',')[0]?.split('-')[0] || 'en';
	
	// Set locale for SSR with priority order
	let userLocale = 'en';
	
	if (urlLangParam && supportedLocales.includes(urlLangParam)) {
		userLocale = urlLangParam;
	} else if (savedLocale && supportedLocales.includes(savedLocale)) {
		userLocale = savedLocale;
	} else if (supportedLocales.includes(browserLocale)) {
		userLocale = browserLocale;
	}
	
	// Set the locale and wait for translations to load
	locale.set(userLocale);
	await waitLocale();
	
	// Get the translation function
	const t = get(_);
	
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

	// Translate the demo chat content for SSR
	const translatedTitle = t(welcomeChat.title);
	const translatedDescription = t(welcomeChat.description);
	const translatedMessages = welcomeChat.messages.map(msg => ({
		...msg,
		content: t(msg.content)
	}));

	// Set cache headers for better SEO (vary by language)
	setHeaders({
		'cache-control': 'public, max-age=3600', // Cache for 1 hour
		'vary': 'Accept-Language' // Different cache per language
	});

	// Return the translated welcome chat data for SSR with SEO metadata
	// This will be pre-rendered in the HTML with actual translated text, making it visible to crawlers
	return {
		welcomeChat: {
			id: welcomeChat.chat_id,
			title: translatedTitle,
			description: translatedDescription,
			keywords: welcomeChat.keywords,
			messages: translatedMessages,
			category: welcomeChat.metadata.category
		},
		seo: {
			title: `OpenMates`,
			description: translatedDescription,
			keywords: welcomeChat.keywords
		}
	};
};

