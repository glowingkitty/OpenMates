/**
 * Preview mock data for ChatMessage.
 *
 * This file provides sample props and named variants for the component preview system.
 * The ChatMessage component renders both user and assistant messages in the chat view.
 * Note: Some features like TipTap rendering require additional context that may not
 * be available in the preview environment.
 * Access at: /dev/preview/ChatMessage
 */

import { embedStore } from '../services/embedStore';
import { settingsDeepLink } from '../stores/settingsDeepLinkStore';

// Preview-only navigation observation for focused click tests.
if (typeof document !== 'undefined') {
	settingsDeepLink.subscribe((path) => {
		document.documentElement.dataset.previewSettingsDeepLink = path ?? '';
	});
}

// Fictional, local-only event data exercises the real results node renderer.
const widthEventId = 'preview-message-width-event';
embedStore.registerStaticEmbed({
	embedId: widthEventId,
	type: 'event',
	appId: 'events',
	content: JSON.stringify({
		type: 'event_result',
		title: 'Local founders meetup',
		provider: 'eventbrite',
		url: 'https://example.org/meetup',
		date_start: '2026-10-06T18:30:00+02:00',
		date_end: '2026-10-06T20:00:00+02:00',
		timezone: 'Europe/Berlin',
		event_type: 'IN_PERSON',
		venue_name: 'Startup hub',
		venue_city: 'Berlin',
		venue_country: 'Germany',
		venue_lat: 52.52,
		venue_lon: 13.405,
	}),
});
const widthResults = '```embeds_results_view\ntitle: Upcoming events\nembeds: ' + widthEventId + '\n```';

/** Default props — shows a user message */
const defaultProps = {
	role: 'user' as const,
	content: 'Can you help me understand how Svelte 5 runes work? I want to migrate my app from Svelte 4.',
	status: 'synced' as const,
	messageParts: [],
	animated: false,
	is_truncated: false,
	containerWidth: 800,
	_embedUpdateTimestamp: 0,
	hasEmbedErrors: false,
	isFirstMessage: false
};

export default defaultProps;

/** Named variants for different message types and states */
export const variants = {
	resultsOnly: {
		...defaultProps, role: 'assistant' as const, content: widthResults,
	},
	shortResults: {
		...defaultProps, role: 'assistant' as const, content: 'Here you go.\n\n' + widthResults,
	},
	workflowResults: {
		...defaultProps, role: 'assistant' as const,
		content: '[View workflow run](/workflows#workflow-id=998a335e-741f-582c-885c-bf61d12ace93&workflow-tab=runs&run-id=118a335e-741f-582c-885c-bf61d12ace93)\n\n' + widthResults,
	},
  focusPhase: {
    ...defaultProps, role: 'system' as const,
    content: JSON.stringify({ type: 'focus_phase_changed', event_id: '11111111-1111-4111-8111-111111111111',
      chat_id: '22222222-2222-4222-8222-222222222222', focus_id: 'jobs-career_insights', phase_id: 'explore',
      phase_title: 'Explore career directions', direction: 'forward', created_at: 1, run_id: 'run', version: 2 }),
  },
  focusPhaseReturn: {
    ...defaultProps, role: 'system' as const,
    content: JSON.stringify({ type: 'focus_phase_changed', event_id: '11111111-1111-4111-8111-111111111111',
      chat_id: '22222222-2222-4222-8222-222222222222', focus_id: 'jobs-career_insights', phase_id: 'understand',
      phase_title: 'Understand your situation', direction: 'backward', created_at: 1, run_id: 'run', version: 3 }),
  },
	/** Assistant message */
	assistant: {
		role: 'assistant' as const,
		content:
			'Svelte 5 runes are a new reactivity system that replaces the old `$:` reactive declarations. ' +
			'Here are the key runes you need to know:\n\n' +
			'- **$state()** — Declares reactive state variables\n' +
			'- **$derived()** — Creates computed values that update automatically\n' +
			'- **$effect()** — Runs side effects when dependencies change\n' +
			'- **$props()** — Declares component props\n\n' +
			'The migration is incremental — your existing Svelte 4 code will continue to work in compatibility mode.',
		status: 'synced' as const,
		model_name: 'claude-sonnet-4-20250514',
		messageParts: [],
		containerWidth: 800,
		isFirstMessage: false
	},

	workflowRun: {
		role: 'assistant' as const,
		content: 'Here are the upcoming events.\n\n[View workflow run](/workflows#workflow-id=998a335e-741f-582c-885c-bf61d12ace93&workflow-tab=runs&run-id=118a335e-741f-582c-885c-bf61d12ace93)',
		status: 'synced' as const,
		messageParts: [],
		containerWidth: 800,
		isFirstMessage: false
	},

	/** Ratios next to prose and other formulas in a shared assistant message. */
	inlineRatioMath: {
		role: 'assistant' as const,
		content:
			'Menschen bevorzugen nicht universell Rechtecke im Verhältnis $1:1{,}618$. ' +
			'Je nach Kontext werden oft Seitenverhältnisse wie $1:1{,}414$ ' +
			'(das DIN-Format $\\sqrt{2}$) oder $1:1{,}5$ angenehm empfunden.',
		status: 'synced' as const,
		messageParts: [],
		containerWidth: 800,
		isFirstMessage: false
	},

	/** Streaming message */
	streaming: {
		role: 'assistant' as const,
		content: 'Let me look into that for you. First, I will search for',
		status: 'streaming' as const,
		model_name: 'claude-sonnet-4-20250514',
		messageParts: [],
		containerWidth: 800,
		animated: true
	},

	/** Processing/waiting message */
	processing: {
		role: 'assistant' as const,
		content: '',
		status: 'processing' as const,
		model_name: 'claude-sonnet-4-20250514',
		messageParts: [],
		containerWidth: 800
	},

	/** Failed message */
	failed: {
		role: 'user' as const,
		content: 'This message failed to send.',
		status: 'failed' as const,
		messageParts: [],
		containerWidth: 800
	},

	/** Sending message */
	sending: {
		role: 'user' as const,
		content: 'This message is being sent...',
		status: 'sending' as const,
		messageParts: [],
		containerWidth: 800
	},

	/** Message with thinking content */
	withThinking: {
		role: 'assistant' as const,
		content:
			'Based on my analysis, the best approach would be to start by converting your reactive declarations first.',
		status: 'synced' as const,
		model_name: 'claude-sonnet-4-20250514',
		thinkingContent:
			'The user wants to migrate from Svelte 4 to Svelte 5. I should explain the key differences ' +
			'and provide a step-by-step migration approach. The most important change is the runes system.',
		isThinkingStreaming: false,
		messageParts: [],
		containerWidth: 800
	},

	/** Truncated message */
	truncated: {
		role: 'assistant' as const,
		content: 'This is a truncated message that was too long to display in full...',
		status: 'synced' as const,
		is_truncated: true,
		messageParts: [],
		containerWidth: 800
	},

	/** User message with sender name */
	withSenderName: {
		role: 'user' as const,
		content: 'What do you think about this approach?',
		status: 'synced' as const,
		sender_name: 'Alex',
		messageParts: [],
		containerWidth: 800
	},
	teamOwnHuman: {
		...defaultProps,
		content: 'I can check the venue near Alexanderplatz.',
		sender_name: 'Alex',
		isOwnUserMessage: true,
	},
	teamRemoteHuman: {
		...defaultProps,
		content: 'I can invite the Berlin volunteers.',
		sender_name: 'Sam',
		isOwnUserMessage: false,
		teamId: 'preview-team',
		senderUserId: 'member-preview',
	},
	teamRemoteWithAvatar: {
		...defaultProps,
		content: 'I uploaded my profile image for the team.',
		sender_name: 'Sam',
		isOwnUserMessage: false,
		teamId: 'preview-team',
		senderUserId: 'member-preview',
		remoteHumanAvatarUrl: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="64" height="64"%3E%3Ccircle cx="32" cy="32" r="32" fill="%234d73ff"/%3E%3C/svg%3E',
	},
	teamOpenMatesMention: {
		...defaultProps,
		content: 'Please ask @openmates about the Team settings.',
	},
	teamAssistant: {
		...defaultProps,
		role: 'assistant' as const,
		content: 'Alex proposed checking the venue; Sam offered to invite volunteers.',
		sender_name: 'Sophia',
		category: 'general_knowledge',
	},

	/** Assistant message with category */
	withCategory: {
		role: 'assistant' as const,
		content: 'Here is the code you requested.',
		status: 'synced' as const,
		category: 'code',
		model_name: 'claude-sonnet-4-20250514',
		messageParts: [],
		containerWidth: 800
	},

	/** Message with embed errors */
	withEmbedErrors: {
		role: 'assistant' as const,
		content: 'I tried to search for that but encountered some issues.',
		status: 'synced' as const,
		hasEmbedErrors: true,
		messageParts: [],
		containerWidth: 800
	},

	/** First message — delete disabled */
	firstMessage: {
		role: 'user' as const,
		content: 'Hello! This is the first message in the conversation.',
		status: 'synced' as const,
		messageParts: [],
		containerWidth: 800,
		isFirstMessage: true
	}
};
