// frontend/apps/web_app/src/routes/(seo)/demo/chat/[slug]/+page.server.ts
//
// Server-side data loader for SEO demo chat pages at /demo/chat/[slug].
//
// ARCHITECTURE — Option 1 (SEO page + redirect):
//   1. The server fetches full demo chat data from the backend API.
//   2. This data is rendered into server-side HTML for Google/crawlers to index.
//   3. A lightweight <script> in +page.svelte redirects human browsers to the
//      main SPA at /#chat-id={slug}, where the full interactive experience lives.
//   4. Crawlers don't execute JavaScript, so they see the full indexed content.
//      Human users are redirected before the page fully renders — seamless.
//
// CACHE STRATEGY:
//   - Prerendered pages (known slugs at build time): served as static files, no SSR cost.
//   - SSR fallback (new slugs added after last build): s-maxage=3600 so CDN caches for 1h.

import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { getBackendUrl } from '$lib/backendUrl';

/** Shape of a single message as returned by the backend demo API. */
interface DemoMessage {
	message_id: string;
	role: 'user' | 'assistant' | 'system';
	content: string;
	category?: string;
	model_name?: string;
	created_at?: number;
}

/** Shape of the full demo chat response from GET /v1/demo/chat/{slug}. */
interface DemoChatResponse {
	demo_id: string;
	slug: string;
	title: string;
	summary: string;
	category?: string;
	icon?: string;
	demo_chat_category?: string;
	content_hash: string;
	follow_up_suggestions: string[];
	updated_at?: string;
	created_at?: string;
	chat_data: {
		chat_id: string;
		messages: DemoMessage[];
		embeds: unknown[];
		encryption_mode: string;
	};
}

export const load: PageServerLoad = async ({ params, fetch, setHeaders, url }) => {
	const { slug } = params;

	// Validate slug format — must start with 'demo-' to match isPublicChat() on the frontend
	if (!slug || !slug.startsWith('demo-')) {
		error(404, 'Demo chat not found');
	}

	// Detect development/staging hostnames so the page can emit noindex meta tags.
	// Matches the same logic used in robots.txt/+server.ts.
	const hostname = url.hostname;
	const isDevHost =
		hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';

	const backendUrl = getBackendUrl(url);

	let chatData: DemoChatResponse;

	try {
		const response = await fetch(`${backendUrl}/v1/demo/chat/${encodeURIComponent(slug)}?lang=en`);

		if (response.status === 404) {
			error(404, 'Demo chat not found');
		}

		if (!response.ok) {
			throw new Error(`Backend returned ${response.status} for demo chat ${slug}`);
		}

		chatData = await response.json();
	} catch (err) {
		// Re-throw SvelteKit errors (404 etc.) directly
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		console.error(`[demo/chat/${slug}] Failed to fetch demo chat data:`, err);
		error(500, 'Failed to load demo chat');
	}

	// Set cache headers for SSR fallback responses (prerendered pages ignore this).
	// s-maxage=3600: CDN caches for 1 hour. stale-while-revalidate=86400: serve stale
	// for up to 24h while fetching a fresh copy in the background.
	setHeaders({
		'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'
	});

	// Build the canonical URL for this page
	const siteOrigin = url.origin;
	const canonicalUrl = `${siteOrigin}/demo/chat/${slug}`;

	// Build JSON-LD structured data.
	// Use TechArticle for learn/features/example_chats, NewsArticle for news category,
	// generic Article for for_everyone/for_developers.
	const category = chatData.demo_chat_category || 'for_everyone';
	const schemaType =
		category === 'news'
			? 'NewsArticle'
			: category === 'learn' || category === 'features' || category === 'example_chats'
				? 'TechArticle'
				: 'Article';

	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': schemaType,
		headline: chatData.title,
		description: chatData.summary || chatData.title,
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
		mainEntityOfPage: {
			'@type': 'WebPage',
			'@id': canonicalUrl
		},
		...(chatData.updated_at && { dateModified: chatData.updated_at }),
		...(chatData.created_at && { datePublished: chatData.created_at })
	};

	// Filter out system messages — they contain internal metadata not useful for SEO display
	const visibleMessages = (chatData.chat_data?.messages || []).filter((m) => m.role !== 'system');

	return {
		slug,
		title: chatData.title,
		summary: chatData.summary || '',
		category: chatData.category || '',
		demoChatCategory: chatData.demo_chat_category || 'for_everyone',
		icon: chatData.icon || '',
		followUpSuggestions: chatData.follow_up_suggestions || [],
		messages: visibleMessages,
		canonicalUrl,
		jsonLd: JSON.stringify(jsonLd),
		// True on dev/staging hostnames — page.svelte emits noindex meta to prevent
		// Google from indexing preview deployments.
		isDevHost,
		// The SPA deep link URL — used by the redirect script in +page.svelte
		// Format: /#chat-id={slug} which the existing processDeepLink handler in +page.svelte
		// recognises and uses to pre-load the demo chat in the SPA
		spaUrl: `${siteOrigin}/#chat-id=${encodeURIComponent(slug)}`
	};
};
