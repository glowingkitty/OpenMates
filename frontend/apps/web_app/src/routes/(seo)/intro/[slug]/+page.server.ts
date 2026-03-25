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
//   for-everyone          → demo-for-everyone
//   for-developers        → demo-for-developers
//   who-develops-openmates → demo-who-develops-openmates
//
// SEE ALSO: +page.ts (prerender config), +page.svelte (HTML + redirect)
// Architecture reference: docs/architecture/web-app

import { error } from '@sveltejs/kit';
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
 * Resolved English content for all 3 intro chats.
 *
 * Content sourced from:
 *   frontend/packages/ui/src/i18n/locales/en.json → demo_chats.{section}.*
 *
 * When i18n content changes, update both the locale JSON and this map.
 */
const INTRO_CHAT_CONTENT: Record<string, IntroChatContent> = {
	'for-everyone': {
		chatId: 'demo-for-everyone',
		title: 'OpenMates | For everyone',
		description: 'AI chatbots made accessible with apps, privacy, and no subscription required',
		message: `# ✨ Digital team mates for everyone

With OpenMates you have a team of specialized AI chatbots that can not only inspire you & teach new knowledge but also fulfill various tasks using apps. Making the power of AI truly accessible for everyone.

## A team of specialized AI chatbots

Different AI chatbots have different strengths and weaknesses. OpenMates combines the best of all worlds by giving you a team of specialized AI chatbots (called "mates"), each with their own set of skills, focus modes, and settings & memories.

## Apps: the superpower of OpenMates

What makes OpenMates different from other AI apps is that your mates can use apps - tools that give them superpowers like browsing the web, reading scientific papers, generating images, analyzing videos, tracking your fitness or nutrition, and much more!

## Privacy & encryption

OpenMates is built with privacy in mind. Your conversations are end-to-end encrypted by default - only you can read them. OpenMates uses zero-knowledge encryption, meaning even the OpenMates team cannot access your data.

## Pay-per-use - no subscription required

Unlike other AI apps, OpenMates does not require a subscription. You only pay for what you use. Start for free and only add credits when you need them.`,
		followUpSuggestions: [
			'How much does it cost?',
			'What apps are available?',
			'Tell me more about privacy'
		]
	},
	'for-developers': {
		chatId: 'demo-for-developers',
		title: 'OpenMates | For developers',
		description:
			'AI-powered development tools with REST API, CLI, privacy, and no MCP setup needed',
		message: `# 👨‍💻 Digital team mates for developers

OpenMates is also an awesome tool for developers. For everything from quick questions, planning large projects, generating code based on the most up-to-date documentation, and much more.

## REST API & CLI

OpenMates provides a REST API and CLI for developers who want to integrate OpenMates into their own projects or automate tasks. No MCP setup required.

## Privacy & open source

Your code and conversations stay private with zero-knowledge encryption. OpenMates is open source — you can inspect the code, contribute, or self-host your own instance.

## No subscription required

Pay only for what you use. Start for free with no credit card required.`,
		followUpSuggestions: [
			'How does the REST API work?',
			'Is my code kept private?',
			'How can I self-host OpenMates?'
		]
	},
	'who-develops-openmates': {
		chatId: 'demo-who-develops-openmates',
		title: 'Who develops OpenMates?',
		description: 'Meet the creator of OpenMates and learn about the philosophy behind the project',
		message: `# 👋 Who develops OpenMates?

Hello!
Marco here (aka glowingkitty). Designer, software architect, maker. And the creator of OpenMates.

We all have our share of frustrations with technology — apps that disrespect your privacy, subscriptions that nickel-and-dime you, AI tools locked behind walled gardens. OpenMates is my answer to that.

## The philosophy

OpenMates is built on a simple belief: powerful AI tools should be accessible to everyone, private by design, and open to the community. No dark patterns, no data harvesting, no lock-in.

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
