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
import { createAssistantRenderPlan } from '../message_parsing/streamingMessageBlocks';
import { parse as parseYaml } from 'yaml';
import { communityGardenWelcomeMelodyChat as mediaMusic } from '../demo_chats/data/example_chats/community-garden-welcome-melody';
import { communityGardenVolunteerChimeChat as mediaAudio } from '../demo_chats/data/example_chats/community-garden-volunteer-chime';
import { communityGardenSunflowerIllustrationChat as mediaImage } from '../demo_chats/data/example_chats/community-garden-sunflower-illustration';
import musicSource from '../i18n/sources/example_chats/community_garden_welcome_melody.yml?raw';
import audioSource from '../i18n/sources/example_chats/community_garden_volunteer_chime.yml?raw';
import imageSource from '../i18n/sources/example_chats/community_garden_sunflower_illustration.yml?raw';
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

const responseSource = [
  'I will compare two sources.',
  '',
  '```json',
  '{"type":"app_skill_use","embed_id":"preview-skill-web","app_id":"web","skill_id":"search"}',
  '```',
  '',
  '```json',
  '{"type":"app_skill_use","embed_id":"preview-skill-news","app_id":"news","skill_id":"search"}',
  '```',
  '',
  'The first comparison is ready.',
  '',
  '```json',
  '{"type":"app_skill_use","embed_id":"preview-skill-images","app_id":"images","skill_id":"search"}',
  '```',
  '',
  'The answer keeps both results in source order.',
].join('\n');
for (const [embedId, appId] of [
  ['preview-skill-web', 'web'], ['preview-skill-news', 'news'], ['preview-skill-images', 'images'],
]) {
  embedStore.registerStaticEmbed({
    embedId, type: 'app-skill-use', appId,
    content: JSON.stringify({ type: 'app_skill_use', title: `Local ${appId} result`, status: 'finished' }),
  });
}
const responseDocument = createAssistantRenderPlan(responseSource, { phase: 'final' }).document;
const streamingResponseSource = responseSource
  .slice(0, responseSource.indexOf('\n\nThe answer keeps both results'))
  .replace(
    '{"type":"app_skill_use","embed_id":"preview-skill-images","app_id":"images","skill_id":"search"}',
    '{"type":"app_skill_use","embed_id":"preview-streaming-skill-images","app_id":"images","skill_id":"search","status":"processing"}',
  );
const streamingResponseDocument = createAssistantRenderPlan(
  streamingResponseSource,
  { phase: 'streaming' },
).document;
const workingResponseDocument = createAssistantRenderPlan([
  'I will create an illustration.', '', '```json',
  '{"type":"app_skill_use","embed_id":"preview-working-skill-images","app_id":"images","skill_id":"generate","status":"processing"}',
  '```',
].join('\n'), { phase: 'streaming' }).document;

// The authored attributes intentionally stay processing after the store finishes.
const liveSkillSource = ['preview-live-first', 'preview-live-second'].map((embedId, index) => [
  '```json',
  JSON.stringify({ type: 'app_skill_use', embed_id: embedId, app_id: index ? 'news' : 'web',
    skill_id: 'search', status: 'processing' }),
  '```',
].join('\n')).join('\n\n');
const liveSkillDocument = createAssistantRenderPlan(liveSkillSource, { phase: 'streaming' }).document;
const seedLiveSkill = (embedId: string, status: string) => embedStore.setInMemoryOnly(`embed:${embedId}`, {
  embed_id: embedId, type: 'app-skill-use', status,
  app_id: embedId.endsWith('first') ? 'web' : embedId.endsWith('second') ? 'news' : 'images',
  skill_id: embedId.startsWith('preview-working-') ? 'generate' : 'search',
  content: JSON.stringify({ type: 'app_skill_use', title: embedId, status }),
});
for (const embedId of ['preview-streaming-skill-images', 'preview-working-skill-images']) {
  seedLiveSkill(embedId, 'processing');
}
seedLiveSkill('preview-live-first', 'finished');
seedLiveSkill('preview-live-second', 'processing');
if (typeof document !== 'undefined') {
  document.addEventListener('preview:finish-second-skill', () => seedLiveSkill('preview-live-second', 'finished'));
}

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

// Real retained generation fixtures, including an echoed parent link from older
// saved/live responses. The result child must stay inline after deduplication.
function generatedMediaPreview(fixture: typeof mediaMusic, source: string, streaming = false) {
  const parent = fixture.embeds.find(embed => !embed.parent_embed_id)!;
  for (const embed of fixture.embeds) embedStore.registerStaticEmbed({
    embedId: embed.embed_id, type: embed.type, content: embed.content,
    parentEmbedId: embed.parent_embed_id, embedIds: embed.embed_ids,
  });
  const markdown = `${parseYaml(source).message_2.en}\n\n[!](embed:${parent.embed_id})`;
  return { ...defaultProps, role: 'assistant' as const,
    content: createAssistantRenderPlan(markdown, { phase: streaming ? 'streaming' : 'final', chatId: fixture.chat_id }).document,
    status: streaming ? 'streaming' as const : 'synced' as const,
    original_message: { chat_id: fixture.chat_id, created_at: 1, role: 'assistant', content: markdown } };
}

/** Named variants for different message types and states */
export const variants = {
  generatedMusic: generatedMediaPreview(mediaMusic, musicSource),
  generatedAudio: generatedMediaPreview(mediaAudio, audioSource),
  generatedImage: generatedMediaPreview(mediaImage, imageSource),
  generatedMusicStreaming: generatedMediaPreview(mediaMusic, musicSource, true),
  voiceUserSending: {
    ...defaultProps, content: 'Spoken words', status: 'sending' as const,
    original_message: { message_id: 'voice-user', chat_id: 'preview-chat', role: 'user' as const,
      call_persistence_v1: { call_id: 'preview-call', typed_pending: false, entries: [] } },
  },
  voiceAssistantStreaming: {
    ...defaultProps, role: 'assistant' as const, content: 'Spoken response', status: 'streaming' as const,
    original_message: { message_id: 'voice-assistant', chat_id: 'preview-chat', role: 'assistant' as const,
      call_persistence_v1: { call_id: 'preview-call', typed_pending: false, entries: [] } },
  },
  voiceAssistantSending: {
    ...defaultProps, role: 'assistant' as const, content: 'Saved response', status: 'sending' as const,
    original_message: { message_id: 'voice-assistant-final', chat_id: 'preview-chat', role: 'assistant' as const,
      call_persistence_v1: { call_id: 'preview-call', typed_pending: false, entries: [] } },
  },
  typedCallSending: {
    ...defaultProps, content: 'Typed while calling', status: 'sending' as const,
    original_message: { message_id: 'typed-call-user', chat_id: 'preview-chat', role: 'user' as const,
      call_persistence_v1: { call_id: 'preview-call', typed_pending: true, entries: [] } },
  },
  typedAcceptedSending: {
    ...defaultProps, content: 'Accepted typed call input', status: 'sending' as const,
    original_message: { message_id: 'typed-accepted-user', chat_id: 'preview-chat', role: 'user' as const,
      call_persistence_v1: { call_id: 'preview-call', typed_pending: false, entries: [] } },
  },
  openmatesOfficial: {
    ...defaultProps, role: 'assistant' as const, category: 'openmates_official',
    content: 'A reply from OpenMates.',
  },
  importedChatGPT: {
    ...defaultProps, role: 'assistant' as const, category: 'chatgpt',
    content: 'A preserved imported reply.',
  },
  namedAssistant: {
    ...defaultProps, role: 'assistant' as const, sender_name: 'Casey',
    content: 'A reply with an explicit sender.',
  },
  completedFocusSubChats: {
    ...defaultProps, role: 'assistant' as const,
    content: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'embed', attrs: {
      type: 'focus-mode-activation', id: 'preview-legacy-focus', app_id: 'web', focus_id: 'web-research', focus_mode_name: 'Deep research', status: 'finished',
    } }] }, { type: 'paragraph', content: [{ type: 'text', text: 'A concise research answer.' }] }] },
    original_message: { chat_id: 'demo-activity-parent', created_at: 1781095355, role: 'assistant', content: '' },
  },
	anonymousFeatureNotice: {
		...defaultProps,
		role: 'system' as const,
		content: JSON.stringify({ type: 'anonymous_feature_notice' }),
	},
	resultsOnly: {
		...defaultProps, role: 'assistant' as const, content: widthResults,
	},
	shortResults: {
		...defaultProps, role: 'assistant' as const, content: 'Here you go.\n\n' + widthResults,
	},
	workflowResults: {
		...defaultProps, role: 'assistant' as const,
		content: '[View workflow run](/workflows#workflow-id=998a335e-741f-582c-885c-bf61d12ace93&workflow-tab=runs&run-id=118a335e-741f-582c-885c-bf61d12ace93&workflow-name=Upcoming+events&workflow-description=Find+relevant+events%0Aand+send+a+short+summary&run-started=1791745200)\n\n' + widthResults,
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
		content: 'Here are the upcoming events.\n\n[View workflow run](/workflows#workflow-id=998a335e-741f-582c-885c-bf61d12ace93&workflow-tab=runs&run-id=118a335e-741f-582c-885c-bf61d12ace93&workflow-name=Upcoming+events&workflow-description=Find+relevant+events%0Aand+send+a+short+summary&run-started=1791745200)',
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

	/** Accepted server turn before the first persisted assistant chunk. */
	responseThinking: {
		role: 'assistant' as const, content: '', status: 'processing' as const,
		isTransientResponse: true, model_name: 'claude-sonnet-4-20250514', server_region: 'EU',
		containerWidth: 800,
	},
	/** User-visible reasoning still streams after the first assistant row exists. */
	responseStreamingReasoning: {
		role: 'assistant' as const, content: '', status: 'streaming' as const,
		thinkingContent: 'I am checking the available sources.', isThinkingStreaming: true,
		model_name: 'claude-sonnet-4-20250514', server_region: 'EU', containerWidth: 800,
	},
	/** Source-ordered active skill calls and prose in one response container. */
	responseStreaming: {
		role: 'assistant' as const, content: streamingResponseDocument, status: 'streaming' as const,
		model_name: 'claude-sonnet-4-20250514', server_region: 'EU', containerWidth: 800,
		thinkingContent: 'I will compare the available sources.', isThinkingStreaming: false,
	},
	responseLiveSkillCompletion: {
		role: 'assistant' as const, content: liveSkillDocument, status: 'streaming' as const,
		model_name: 'claude-sonnet-4-20250514', server_region: 'EU', containerWidth: 800,
	},
	/** Action skill IDs keep the active footer in Working, not Researching. */
	responseWorking: {
		role: 'assistant' as const, content: workingResponseDocument, status: 'streaming' as const,
		model_name: 'claude-sonnet-4-20250514', server_region: 'EU', containerWidth: 800,
	},
	/** Completed activity collapses at its authored position and can be expanded. */
	responseCompleted: {
		role: 'assistant' as const, content: responseDocument, status: 'synced' as const,
		model_name: 'claude-sonnet-4-20250514', server_region: 'EU', containerWidth: 800,
		thinkingContent: 'I will compare the available sources.', isThinkingStreaming: false,
	},
	/** A finished response with visible thinking and no app calls uses the same disclosure. */
	responseThinkingOnlyCompleted: {
		role: 'assistant' as const, content: 'A concise answer.', status: 'synced' as const,
		containerWidth: 800, thinkingContent: 'I checked the wording before answering.',
		isThinkingStreaming: false,
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
	teamRemoteQueued: {
		...defaultProps,
		content: 'Sam’s queued follow-up.',
		status: 'queued' as const,
		messageId: 'preview-remote-queued',
		currentChatId: 'preview-team-chat',
		sender_name: 'Sam',
		isOwnUserMessage: false,
		teamId: 'preview-team',
		senderUserId: 'member-preview',
		original_message: {
			message_id: 'preview-remote-queued', chat_id: 'preview-team-chat', role: 'user' as const,
			content: 'Sam’s queued follow-up.', status: 'queued' as const, created_at: 1,
			queue_revision: 1, queue_mode: 'follow_up' as const,
			hashed_user_id: 'another-team-member',
		},
		queueActions: {
			mode: 'follow_up' as const, busy: false, error: null,
			onEdit: () => {}, onSteer: () => {},
		},
	},
	teamOwnPaused: {
		...defaultProps,
		content: 'Saved question with no assistant handoff.',
		messageId: 'preview-own-paused',
		currentChatId: 'preview-team-chat',
		teamId: 'preview-team',
		isOwnUserMessage: true,
		original_message: {
			message_id: 'preview-own-paused', chat_id: 'preview-team-chat', role: 'user' as const,
			content: 'Saved question with no assistant handoff.', status: 'synced' as const,
			created_at: 1, queue_dispatch_status: 'paused' as const,
		},
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
