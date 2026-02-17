/**
 * Preview mock data for ChatMessage.
 *
 * This file provides sample props and named variants for the component preview system.
 * The ChatMessage component renders both user and assistant messages in the chat view.
 * Note: Some features like TipTap rendering require additional context that may not
 * be available in the preview environment.
 * Access at: /dev/preview/ChatMessage
 */

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
