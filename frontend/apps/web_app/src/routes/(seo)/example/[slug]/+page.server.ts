// frontend/apps/web_app/src/routes/(seo)/example/[slug]/+page.server.ts
//
// Server-side data loader for individual example chat SEO pages at /example/[slug].
// All data comes from static hardcoded example chats — no backend API calls needed.
//
// ARCHITECTURE:
//   1. Loads example chat data from the static exampleChatStore (imported at build time).
//   2. Renders full chat content to HTML for Google/crawlers to index.
//   3. Human browsers are redirected to the SPA via onMount in +page.svelte.
//
// CACHE: Prerendered pages are static files. SSR fallback uses s-maxage=86400 (24h CDN).

import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { getExampleChatBySlug, resolveExampleChatI18nKey as t } from '@repo/ui';
import { getSiteOrigin } from '$lib/backendUrl';

export const load: PageServerLoad = async ({ params, setHeaders, url }) => {
	const { slug } = params;

	const chat = getExampleChatBySlug(slug);
	if (!chat) {
		error(404, 'Example chat not found');
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
	const canonicalUrl = `${siteOrigin}/example/${slug}`;

	const title = t(chat.title);
	const summary = t(chat.summary);

	// Build JSON-LD structured data for rich search results
	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': 'Article',
		headline: title,
		description: summary,
		keywords: chat.keywords.join(', '),
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
		}
	};

	// Translate and filter messages for SEO display
	// User messages: resolve i18n keys. Assistant messages: extract query text from JSON tool calls.
	const visibleMessages = chat.messages.map(msg => {
		let displayContent = t(msg.content);

		// For assistant messages that are only JSON tool calls, extract a human-readable summary
		if (msg.role === 'assistant') {
			const lines = msg.content.split('\n');
			const textLines: string[] = [];
			let inCodeBlock = false;

			for (const line of lines) {
				if (line.startsWith('```')) {
					inCodeBlock = !inCodeBlock;
					continue;
				}
				if (!inCodeBlock && line.trim()) {
					textLines.push(line);
				}
			}

			// If there are non-code text lines, use those
			if (textLines.length > 0) {
				displayContent = textLines.join('\n');
			} else {
				// All content is code blocks (tool calls) — extract queries for SEO
				const queryMatches = [...msg.content.matchAll(/"query"\s*:\s*"([^"]+)"/g)];
				if (queryMatches.length > 0) {
					displayContent = queryMatches.map(m =>
						`Searched: ${m[1]}`
					).join('\n');
				}
			}
		}

		return {
			role: msg.role,
			content: displayContent
		};
	});

	return {
		slug,
		title,
		summary,
		icon: chat.icon,
		category: chat.category,
		keywords: chat.keywords,
		followUpSuggestions: chat.follow_up_suggestions.map(t),
		messages: visibleMessages,
		canonicalUrl,
		jsonLd: JSON.stringify(jsonLd),
		isDevHost,
		// The SPA deep link — redirects human browsers to the interactive chat view
		spaUrl: `${siteOrigin}/#chat-id=${encodeURIComponent(chat.chat_id)}`
	};
};
