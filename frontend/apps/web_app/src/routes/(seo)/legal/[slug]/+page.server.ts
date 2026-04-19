// frontend/apps/web_app/src/routes/(seo)/legal/[slug]/+page.server.ts
//
// Server-side loader for legal document SEO pages at /legal/{slug}.
// Accepts slugs: privacy, terms, imprint.
//
// ARCHITECTURE — Static SEO page with browser redirect:
//   1. Resolves title/description from the English i18n locale (no backend call).
//   2. Renders HTML with OG meta tags that crawlers and link-preview bots index.
//   3. Human browsers are redirected to the SPA via onMount in +page.svelte.
//      The SPA then calls setActiveChat which uses replaceState to restore the
//      /legal/{slug} path — so the URL stays clean after the redirect round-trip.

import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { getLegalChatBySlug } from '@repo/ui';
import { resolveI18nKey as t } from '@repo/ui/src/demo_chats/resolveI18nServer';
import { getSiteOrigin } from '$lib/backendUrl';

const LEGAL_SLUGS = ['privacy', 'terms', 'imprint'] as const;
type LegalSlug = (typeof LEGAL_SLUGS)[number];

function isLegalSlug(slug: string): slug is LegalSlug {
	return (LEGAL_SLUGS as readonly string[]).includes(slug);
}

export const load: PageServerLoad = async ({ params, setHeaders, url }) => {
	const { slug } = params;

	if (!isLegalSlug(slug)) {
		error(404, 'Legal document not found');
	}

	const chat = getLegalChatBySlug(slug);
	if (!chat) {
		error(404, 'Legal document not found');
	}

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

	const siteOrigin = getSiteOrigin(url);
	const canonicalUrl = `${siteOrigin}/legal/${slug}`;

	const title = t(chat.title);
	// Description is stored under metadata.legal_{slug}.description
	const descriptionKey = `metadata.legal_${slug.replace('-', '_')}.description`;
	const description = t(descriptionKey);

	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': 'WebPage',
		name: title,
		description,
		url: canonicalUrl,
		author: { '@type': 'Organization', name: 'OpenMates', url: siteOrigin },
		publisher: { '@type': 'Organization', name: 'OpenMates', url: siteOrigin },
		mainEntityOfPage: { '@type': 'WebPage', '@id': canonicalUrl }
	};

	return {
		slug,
		title,
		description,
		keywords: chat.keywords,
		canonicalUrl,
		jsonLd: JSON.stringify(jsonLd),
		isDevHost,
		spaUrl: `${siteOrigin}/#chat-id=${encodeURIComponent(chat.chat_id)}`
	};
};
