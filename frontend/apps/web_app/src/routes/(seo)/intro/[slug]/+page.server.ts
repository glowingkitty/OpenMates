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
//   privacy               → demo-privacy
//   safety                → demo-safety
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
 * Resolved English content for all intro chats.
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

Different AI chatbots have different strengths and weaknesses. OpenMates combines the best of all worlds by giving you a team of specialized AI chatbots (called "mates"), each with their own set of skills, focus modes, and memories.

## Apps: the superpower of OpenMates

What makes OpenMates different from other AI apps is that your mates can use apps - tools that give them superpowers like browsing the web, reading scientific papers, generating images, analyzing videos, tracking your fitness or nutrition, and much more!

## Privacy & encryption

OpenMates is built with privacy in mind. Your chats, titles, app settings, and memories are **encrypted in your browser before being sent to our servers** — and are stored only as ciphertext. When you need an AI response, our servers briefly decrypt your content in memory, use it, and discard the plaintext without ever writing it to disk. Before your prompts reach any third-party AI model, real names, emails, and addresses are replaced with placeholders on your device. This is not end-to-end encryption (our servers can decrypt your content transiently to serve you), but it is a much stronger guarantee than encryption-at-rest alone — and when you delete your account, destroying your encryption key cryptographically shreds every encrypted field we still hold.

## Pay-per-use - no subscription required

Unlike other AI apps, OpenMates does not require a subscription. You only pay for what you use. Start for free and only add credits when you need them.`,
		followUpSuggestions: [
			'How much does it cost?',
			'What apps are available?',
			'Tell me more about privacy'
		]
	},
	privacy: {
		chatId: 'demo-privacy',
		title: 'OpenMates | Privacy',
		description:
			'How OpenMates protects your chats, memories, drafts, and personal data before it reaches our servers or AI providers',
		message: `# Privacy built into the product

OpenMates is designed so your private data is protected before it is stored, synced, or sent to an AI model.

The short version: your chats, memories, app settings, personal privacy settings, and signed-in drafts are encrypted before they are synced. Before a message is sent, your browser can also replace detected personal data with placeholders so OpenMates servers and AI providers receive the safer placeholder version instead of the detected original values.

This page explains the product protections in plain English. The full legal details, provider list, retention rules, and your legal rights stay in the [Privacy Policy](/legal/privacy).

## Personal data replacement before a message leaves your browser

When you send a message, OpenMates scans it on your device for personal or sensitive data. Detected values are replaced with placeholders before the message is sent to OpenMates.

Examples include emails, phone numbers, API keys, private keys, credit card numbers, IP addresses, bank account numbers, tax IDs, passport numbers, and similar patterns.

You can also teach OpenMates what matters to you. In Privacy settings you can add names, addresses, birthdays, and custom private values that should be detected more reliably on your device. These custom entries are encrypted before they sync, just like other private settings.

The mapping from placeholder back to the original value is encrypted with your key. That lets your browser restore the original value for you while keeping the raw value away from OpenMates servers and AI providers.

Limit: no detector is perfect. If you type a value in an unusual format, include someone else's personal information, or write something sensitive that is not formally identifiable data, OpenMates may not detect it. Treat every message as something that may be processed by an AI provider unless you see it replaced before sending.

## Encrypted chats, memories, and signed-in drafts

Your chat content is encrypted in your browser before it is synced. Your memories, sensitive app settings, privacy settings, and signed-in drafts are also encrypted before storage or sync.

For signed-in users, draft text and draft previews are encrypted before being saved for cross-device sync. PII replacement happens when you send a message; an unsent draft may still contain the original values, but the synced draft itself is encrypted before it leaves your browser.

Logged-out drafts are different: they stay only in your browser's local session storage and are not synced to OpenMates.

## Honest encryption model

OpenMates is not end-to-end encrypted. Our servers must briefly decrypt some content in memory to do the job you asked for, such as generating an AI response, rendering an invoice, or delivering a reminder.

The important difference is that plaintext is not written to disk, logs, traces, or backups. Stored chat content is ciphertext. If someone only gets access to the database or backups, they should not be able to read your past chats without your key.

## No tracking business model

OpenMates is not funded by ads or selling user data. We do not use Google Analytics, PostHog, Plausible, Segment, or similar third-party analytics SDKs in the app.

Operational logging exists so the service can work, detect abuse, and debug failures, but it is designed to avoid storing chat content and to minimize user identifiers.

## Account deletion

When you delete your account, OpenMates deletes the account data we control: chats, messages, embeds, drafts, memories, app settings, usage rows, device/session data, API keys, passkeys, and related sync data.

We also delete the encryption key. That means any leftover encrypted backup or stale cache copy becomes unreadable ciphertext.

Some limited records can remain for legal, security, or provider-side reasons, such as invoice records, security audit logs, short-lived AI provider request logs, redacted observability traces, or encrypted backups until their lifecycle expires. The exact list belongs in the [Privacy Policy](/legal/privacy), not on this intro page.`,
		followUpSuggestions: [
			'How does PII replacement work?',
			'What exactly is encrypted?',
			'What remains after account deletion?'
		]
	},
	safety: {
		chatId: 'demo-safety',
		title: 'OpenMates | Safety',
		description:
			'How OpenMates reduces harmful instructions, hallucinations, unsafe advice, and prompt injection risks',
		message: `# Safer AI by design

AI chatbots can be useful, but they can also be wrong, overconfident, manipulated, or unsafe. OpenMates does not treat the model as a trusted authority. We add safety checks around the model so risky requests, external content, tool use, and sensitive topics get extra handling.

These systems reduce risk. They do not make AI perfect, and they do not replace professional help, careful verification, or common sense.

## Harmful instructions and misuse

Before the main AI response runs, OpenMates analyzes the request for harmful or illegal intent and for misuse risk.

Harmful or illegal requests can be refused before they reach the normal answer path. Misuse risk is handled separately, so requests that could enable scams, hacking, or abuse get extra scrutiny even if they are phrased indirectly.

The safety check also tries to preserve legitimate use. For example, harm-reduction or defensive cybersecurity questions are different from instructions to harm someone or break into systems.

## Mental health and crisis situations

Self-harm and crisis messages are not treated as bad user behavior to punish or block. OpenMates routes them toward the psychology and life-coaching area so the response can be more careful and supportive.

For mental-health, medical, legal, and financial topics, OpenMates adds disclaimers through product logic instead of hoping the AI remembers. The AI should not be treated as a therapist, doctor, lawyer, financial adviser, or source of truth about reality.

This matters for AI psychosis risk too. OpenMates should avoid reinforcing delusions, dependency, or claims of special hidden meaning. The product can reduce that risk with routing, disclaimers, and careful instructions, but it cannot guarantee that every AI response is safe for every mental state.

## Hallucinations and wrong sources

AI models sometimes invent facts, links, tool results, or source names. OpenMates reduces this in several ways:

- It narrows available tools before the main model responds.
- It validates tool names instead of allowing arbitrary invented tools.
- It checks provider names against known provider lists.
- It validates markdown links and can replace broken links with search links.

You should still verify important facts, medical/legal/financial advice, and anything that could affect real-world decisions.

## Prompt injection from external content

Websites, PDFs, videos, code, metadata, and search results can contain hidden or visible instructions that try to manipulate the AI. This is called prompt injection.

OpenMates uses multiple defenses:

- Hidden Unicode and ASCII-smuggling characters are stripped.
- External text can be scanned by a safety model for prompt-injection attempts.
- Suspicious injection text can be removed or replaced before it reaches the main model.
- The web interface keeps prompt-injection scanning enforced.

This is especially important because OpenMates apps can read external content for you. The AI should use that content as data, not blindly obey instructions found inside it.

## Prompt injection by the user

Users can also try to manipulate internal routing by asking the preprocessing step to call tools, ignore rules, or reveal hidden data.

OpenMates limits this by isolating preprocessing. The preprocessing model is given one analysis function, not the app tools. If a user tells it to call \`web-search\`, \`images-generate\`, or another tool at that stage, those tools are not available there.

After preprocessing, OpenMates only exposes the main model to tools that were selected as relevant for the request. This reduces the chance of arbitrary or invented tool use.

## Image and file safety

Uploaded files and generated images need their own safety rules. OpenMates scans uploaded media and has a stricter image-generation safety policy for dangerous edits, identity abuse, sexual content involving minors, non-consensual intimate imagery, and other high-risk cases.

Image safety is a separate system because images create different risks than text chat.`,
		followUpSuggestions: [
			'How does prompt injection protection work?',
			'Can OpenMates still hallucinate?',
			'What happens with crisis or mental-health topics?'
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

Your code and conversations are encrypted in your browser before being sent to our servers, and stored only as ciphertext. Our servers decrypt content transiently in memory when you need it (for AI responses, invoices, reminders) and never persist plaintext to disk, logs, or traces. Before prompts reach any third-party AI model, real names, emails, and addresses are replaced with placeholders on your device. OpenMates is open source — you can inspect the exact encryption code, contribute, or self-host your own instance.

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
