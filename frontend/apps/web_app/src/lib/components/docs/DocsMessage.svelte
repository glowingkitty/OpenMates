<script lang="ts">
	/**
	 * DocsMessage Component
	 *
	 * Renders documentation content styled as a single assistant chat message.
	 * Uses ReadOnlyMessage for TipTap-based markdown rendering, wrapped in
	 * the same visual structure as ChatMessage (avatar + sender name + bubble).
	 * The message uses the OpenMates logo (openmates_official) as the avatar,
	 * and respects the same content max-width as ChatHistory for readable line lengths.
	 *
	 * Architecture: docs/architecture/docs-web-app.md
	 * Test: N/A — visual component, tested via E2E
	 */
	import { ReadOnlyMessage, text } from '@repo/ui';

	interface Props {
		/** Original markdown content to render via TipTap */
		content: string;
		/** Category is kept for API compatibility but not used for avatar (always shows OpenMates logo) */
		category: string;
	}

	let { content, category: _category }: Props = $props();
</script>

<div class="docs-message-wrapper">
	<div class="docs-message chat-message assistant">
		<!-- OpenMates logo avatar — same as demo-for-everyone intro chat -->
		<div class="mate-profile openmates_official" style="animation: none; opacity: 1;"></div>

		<div class="message-align-left">
			<div class="mate-message-content" role="article">
				<div class="chat-mate-name">{$text('documentation.sender_name')}</div>
				<div class="chat-message-text">
					<ReadOnlyMessage {content} role="assistant" selectable={true} />
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	/* Width-limiting wrapper — mirrors .chat-history-content in ChatHistory.svelte */
	.docs-message-wrapper {
		width: 100%;
		max-width: var(--chat-content-max-width, 1000px);
		margin: 0 auto;
		padding: 12px 0 2rem;
		box-sizing: border-box;
		min-width: 0;
		overflow-x: hidden;
	}

	.docs-message {
		padding: 0 1rem;
		min-width: 0;
	}

	/* Remove the speech bubble tail for docs — cleaner look for long content */
	.docs-message :global(.mate-message-content::before) {
		display: none;
	}

	/* Remove drop shadow on docs content for a flatter reading experience */
	.docs-message :global(.mate-message-content) {
		filter: none;
		margin-inline-end: 0;
		min-width: 0;
		overflow-x: auto;
	}

	/* Prevent the openmates_official mate-profile AI badge from showing */
	.docs-message :global(.mate-profile::after),
	.docs-message :global(.mate-profile::before) {
		display: none !important;
	}
</style>
