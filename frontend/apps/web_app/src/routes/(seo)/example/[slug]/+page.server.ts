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

type ExampleChat = NonNullable<ReturnType<typeof getExampleChatBySlug>>;

type SeoSource = {
	label: string;
	title: string;
	source: string;
	url: string;
	provider: string;
	kind: string;
};

type SeoMessage = {
	role: string;
	content: string;
	sources: SeoSource[];
};

function getLastModifiedDate(chat: ExampleChat): string {
	const latestMessageTimestamp = Math.max(...chat.messages.map((message) => message.created_at), 0);
	if (latestMessageTimestamp <= 0) return new Date().toISOString().split('T')[0];
	return new Date(latestMessageTimestamp * 1000).toISOString().split('T')[0];
}

function stripWrappingQuotes(value: string): string {
	const trimmed = value.trim();
	if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
		return trimmed.slice(1, -1);
	}
	return trimmed;
}

function parseToon(content: string): Record<string, string> {
	const fields: Record<string, string> = {};
	for (const line of content.split('\n')) {
		const match = line.match(/^([a-zA-Z0-9_]+):\s*(.*)$/);
		if (!match) continue;
		fields[match[1]] = stripWrappingQuotes(match[2]);
	}
	return fields;
}

function getHostname(url: string): string {
	try {
		return new URL(url).hostname.replace(/^www\./, '');
	} catch {
		return '';
	}
}

function stripMarkdownForSchema(content: string): string {
	return content
		.replace(/```[\s\S]*?```/g, ' ')
		.replace(/\[!\]\(embed:[^)]+\)/g, ' ')
		.replace(/\[([^\]]+)\]\((?:wiki:)?[^)]+\)/g, '$1')
		.replace(/[*_`#>]/g, '')
		.replace(/\s+/g, ' ')
		.trim();
}

function summarizeJsonToolBlocks(content: string): string {
	const summaries: string[] = [];

	for (const match of content.matchAll(/```json\s*([\s\S]*?)```/g)) {
		try {
			const payload = JSON.parse(match[1]);
			if (payload?.type === 'app_skill_use' && payload.app_id && payload.skill_id) {
				summaries.push(`Used ${payload.app_id}.${payload.skill_id} to retrieve app results.`);
			}
		} catch {
			continue;
		}
	}

	return summaries.join(' ');
}

function buildEmbedRefMap(chat: ExampleChat): Map<string, SeoSource> {
	const byRef = new Map<string, SeoSource>();

	for (const embed of chat.embeds) {
		const fields = parseToon(embed.content);
		const embedRef = fields.embed_ref;
		if (!embedRef) continue;

		const title = fields.title || fields.query || fields.url || fields.source_page_url || embedRef;
		const url = fields.source_page_url || fields.url || fields.image_url || '';
		const source = fields.source || fields.provider || getHostname(url) || 'OpenMates app result';
		const provider = fields.provider || fields.providers || fields.app_id || '';

		byRef.set(embedRef, {
			label: embedRef,
			title,
			source,
			url,
			provider,
			kind: fields.type || embed.type
		});
	}

	return byRef;
}

function summarizeEmbedRefs(content: string, embedRefMap: Map<string, SeoSource>): SeoSource[] {
	const sources: SeoSource[] = [];
	const seen = new Set<string>();
	for (const match of content.matchAll(/\[!\]\(embed:([^)]+)\)/g)) {
		const ref = match[1];
		if (seen.has(ref)) continue;
		seen.add(ref);
		const source = embedRefMap.get(ref);
		if (source) sources.push(source);
	}
	return sources;
}

function removeEmbedRefs(content: string): string {
	return content
		.split('\n')
		.filter((line) => !line.trim().match(/^\[!\]\(embed:[^)]+\)$/))
		.join('\n')
		.replace(/\n{3,}/g, '\n\n')
		.trim();
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
		const toolSummary = summarizeJsonToolBlocks(displayContent);
		if (toolSummary) {
			displayContent = toolSummary;
		}

		const queryMatches = [...displayContent.matchAll(/"query"\s*:\s*"([^"]+)"/g)];
		if (queryMatches.length > 0) {
			displayContent = queryMatches.map((match) => `Searched: ${match[1]}`).join('\n');
		}
	}

	return removeEmbedRefs(displayContent);
}

function buildVisibleMessages(chat: ExampleChat): SeoMessage[] {
	const embedRefMap = buildEmbedRefMap(chat);
	return chat.messages.map((msg) => {
		const translatedContent = t(msg.content);
		return {
			role: msg.role,
			content: toReadableMessageContent(msg.role, msg.content),
			sources: summarizeEmbedRefs(translatedContent, embedRefMap)
		};
	});
}

function buildQuestionAnswerPairs(messages: SeoMessage[]) {
	const pairs: { question: string; answer: string }[] = [];
	for (let i = 0; i < messages.length; i++) {
		const current = messages[i];
		const next = messages[i + 1];
		if (current?.role === 'user' && next?.role === 'assistant') {
			pairs.push({
				question: stripMarkdownForSchema(current.content),
				answer: stripMarkdownForSchema(next.content)
			});
		}
	}
	return pairs.filter((pair) => pair.question && pair.answer);
}

function buildStructuredData({
	title,
	summary,
	canonicalUrl,
	siteOrigin,
	lastModified,
	keywords,
	messages
}: {
	title: string;
	summary: string;
	canonicalUrl: string;
	siteOrigin: string;
	lastModified: string;
	keywords: string[];
	messages: SeoMessage[];
}) {
	const questionAnswerPairs = buildQuestionAnswerPairs(messages);
	const mainEntity = questionAnswerPairs.map((pair) => ({
		'@type': 'Question',
		name: pair.question,
		acceptedAnswer: {
			'@type': 'Answer',
			text: pair.answer
		}
	}));

	return {
		'@context': 'https://schema.org',
		'@graph': [
			{
				'@type': 'QAPage',
				'@id': `${canonicalUrl}#qa`,
				url: canonicalUrl,
				name: `${title} — OpenMates`,
				description: summary,
				image: OG_IMAGE_URL,
				dateModified: lastModified,
				keywords: keywords.join(', '),
				publisher: {
					'@type': 'Organization',
					name: 'OpenMates',
					url: siteOrigin
				},
				mainEntity
			},
			{
				'@type': 'BreadcrumbList',
				'@id': `${canonicalUrl}#breadcrumb`,
				itemListElement: [
					{
						'@type': 'ListItem',
						position: 1,
						name: 'OpenMates',
						item: `${siteOrigin}/`
					},
					{
						'@type': 'ListItem',
						position: 2,
						name: 'Example Chats',
						item: `${siteOrigin}/example`
					},
					{
						'@type': 'ListItem',
						position: 3,
						name: title,
						item: canonicalUrl
					}
				]
			}
		]
	};
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

	const visibleMessages = buildVisibleMessages(chat);
	const jsonLd = buildStructuredData({
		title,
		summary,
		canonicalUrl,
		siteOrigin,
		lastModified,
		keywords: chat.keywords,
		messages: visibleMessages
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
