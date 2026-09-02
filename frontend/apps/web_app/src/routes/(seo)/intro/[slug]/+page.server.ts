// frontend/apps/web_app/src/routes/(seo)/intro/[slug]/+page.server.ts
//
// Server-side data loader for intro chat SEO pages at /intro/[slug].
//
// ARCHITECTURE — Static SEO page with browser redirect:
//   1. This loader resolves all page data from static TypeScript data + English i18n JSON.
//      No backend API call needed — intro chats are bundled with the frontend.
//   2. The resolved data is rendered into server-side HTML that Google/crawlers index.
//   3. A redirect in +page.svelte sends human browsers to the SPA at /#chat-id={chat_id}.
//   4. Crawlers don't execute JavaScript — they see and index the full HTML content.
//
// SLUGS → CHAT_ID mapping:
//   who-develops-openmates → demo-who-develops-openmates
//
// SEE ALSO: +page.ts (prerender config), +page.svelte (HTML + redirect)
// Architecture reference: docs/architecture/web-app

import { error, redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { getSiteOrigin } from '$lib/backendUrl';

/** Static i18n content for each intro chat (English only — SEO pages are English). */
interface IntroChatContent {
	title: string;
	description: string;
	message: string;
	followUpSuggestions: string[];
	/** The SPA chat_id used in /#chat-id={chatId} deep links */
	chatId: string;
}

/**
 * Resolved English content for all intro chats.
 *
 * Content sourced from:
 *   frontend/packages/ui/src/i18n/locales/en.json → demo_chats.{section}.*
 *
 * When i18n content changes, update both the locale JSON and this map.
 */
const INTRO_CHAT_CONTENT: Record<string, IntroChatContent> = {
	'who-develops-openmates': {
		chatId: 'demo-who-develops-openmates',
		title: 'Who develops OpenMates?',
		description: 'Meet the creator of OpenMates and learn about the philosophy behind the project',
		message: `# 👋 Who develops OpenMates?

Hello!
Marco here (aka glowingkitty). Designer, software architect, maker. And the creator of OpenMates.

We all have our share of frustrations with technology — apps that disrespect your privacy, subscriptions that nickel-and-dime you, AI tools locked behind walled gardens. OpenMates is my answer to that.

## The philosophy

OpenMates is built on a simple belief: powerful AI tools should be accessible to everyone, privacy-respecting by design, and open to the community. No dark patterns, no data harvesting, no lock-in.

## Open source

OpenMates is fully open source. The code is on GitHub — you can read it, contribute to it, or run your own instance. Transparency is not optional.

## Built with love

Every feature in OpenMates is designed with care. If something bothers you, there's a good chance it bothers me too — and I'm working on fixing it.`,
		followUpSuggestions: [
			'What is the long-term vision for OpenMates?',
			'How can I contribute to OpenMates?',
			'Why is open source important for OpenMates?'
		]
	}
};

export const load: PageServerLoad = async ({ params, url }) => {
	const { slug } = params;
	if (slug === 'for-everyone' || slug === 'for-developers') {
		redirect(301, '/');
	}

	const content = INTRO_CHAT_CONTENT[slug];
	if (!content) {
		error(404, 'Intro chat not found');
	}

	// Detect development/staging hostnames so the page can emit noindex meta tags.
	// Matches the same logic used in robots.txt/+server.ts and demo/chat/[slug]/+page.server.ts.
	const hostname = url.hostname;
	const isDevHost =
		hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname.endsWith('.vercel.app') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';

	const siteOrigin = getSiteOrigin(url);
	const canonicalUrl = `${siteOrigin}/intro/${slug}`;

	// JSON-LD: WebApplication schema — intro pages describe the app itself, not an article
	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': 'WebApplication',
		name: 'OpenMates',
		headline: content.title,
		description: content.description,
		url: canonicalUrl,
		applicationCategory: 'Productivity',
		operatingSystem: 'Web',
		author: {
			'@type': 'Organization',
			name: 'OpenMates',
			url: siteOrigin
		},
		publisher: {
			'@type': 'Organization',
			name: 'OpenMates',
			url: siteOrigin
		},
		offers: {
			'@type': 'Offer',
			price: '0',
			priceCurrency: 'USD'
		},
		mainEntityOfPage: {
			'@type': 'WebPage',
			'@id': canonicalUrl
		}
	};

	return {
		slug,
		title: content.title,
		description: content.description,
		message: content.message,
		followUpSuggestions: content.followUpSuggestions,
		canonicalUrl,
		jsonLd: JSON.stringify(jsonLd),
		// True on dev/staging hostnames — page.svelte emits noindex meta to prevent
		// Google from indexing preview deployments.
		isDevHost,
		// The SPA deep link URL — used by the redirect in +page.svelte.
		// Format: /#chat-id={chatId} which processDeepLink in the SPA root handles.
		spaUrl: `${siteOrigin}/#chat-id=${encodeURIComponent(content.chatId)}`
	};
};
