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
import { getExampleChatBySlug } from '@repo/ui';
import { resolveExampleChatI18nKey as t } from '@repo/ui/src/demo_chats/resolveI18nServer';
import { getSiteOrigin } from '$lib/backendUrl';

const OG_IMAGE_URL = 'https://openmates.org/images/og-image.jpg';

function getLastModifiedDate(chat: NonNullable<ReturnType<typeof getExampleChatBySlug>>): string {
	const latestMessageTimestamp = Math.max(...chat.messages.map((message) => message.created_at), 0);
	if (latestMessageTimestamp <= 0) return new Date().toISOString().split('T')[0];
	return new Date(latestMessageTimestamp * 1000).toISOString().split('T')[0];
}

function toReadableMessageContent(role: string, content: string): string {
	let displayContent = t(content);

	if (role !== 'assistant') return displayContent;

	const lines = displayContent.split('\n');
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

	if (textLines.length > 0) {
		displayContent = textLines.join('\n');
	} else {
		const queryMatches = [...displayContent.matchAll(/"query"\s*:\s*"([^"]+)"/g)];
		if (queryMatches.length > 0) {
			displayContent = queryMatches.map((match) => `Searched: ${match[1]}`).join('\n');
		}
	}

	return displayContent;
}

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
	const lastModified = getLastModifiedDate(chat);

	// Build JSON-LD structured data for rich search results
	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': 'Article',
		headline: title,
		description: summary,
		image: OG_IMAGE_URL,
		dateModified: lastModified,
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

	const visibleMessages = chat.messages.map(msg => {
		return {
			role: msg.role,
			content: toReadableMessageContent(msg.role, msg.content)
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
		lastModified,
		canonicalUrl,
		ogImageUrl: OG_IMAGE_URL,
		jsonLd: JSON.stringify(jsonLd),
		isDevHost,
		// The SPA deep link — redirects human browsers to the interactive chat view
		spaUrl: `${siteOrigin}/#chat-id=${encodeURIComponent(chat.chat_id)}`
	};
};
