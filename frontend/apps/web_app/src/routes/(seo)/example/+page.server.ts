// frontend/apps/web_app/src/routes/(seo)/example/+page.server.ts
//
// Server-side data loader for the example chat listing page at /example/.
// All data comes from static hardcoded example chats — no backend API calls needed.

import type { PageServerLoad } from './$types';
import { getAllExampleChatData, resolveI18nKey } from '@repo/ui';
import { getSiteOrigin } from '$lib/backendUrl';
// @ts-expect-error — JSON import works at build time
import enLocale from '../../../../../packages/ui/src/i18n/locales/en.json';

function t(key: string): string {
	return resolveI18nKey(key, enLocale);
}

export const load: PageServerLoad = async ({ setHeaders, url }) => {
	const hostname = url.hostname;
	const isDevHost =
		hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname.endsWith('.vercel.app') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';

	setHeaders({
		'Cache-Control': 'public, s-maxage=86400, stale-while-revalidate=604800'
	});

	const allChats = getAllExampleChatData();
	const canonicalUrl = `${getSiteOrigin(url)}/example`;

	return {
		chats: allChats.map(chat => ({
			slug: chat.slug,
			title: t(chat.title),
			summary: t(chat.summary),
			icon: chat.icon,
			category: chat.category,
			keywords: chat.keywords
		})),
		totalCount: allChats.length,
		canonicalUrl,
		isDevHost
	};
};
