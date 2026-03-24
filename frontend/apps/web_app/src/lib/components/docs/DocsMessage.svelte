<script lang="ts">
	/**
	 * DocsMessage Component
	 *
	 * Renders documentation content styled as a single assistant chat message.
	 * Reuses the same classes as the regular chat: chat-history-content for
	 * width-limiting (from ChatHistory.svelte), and chat-message/mate-profile/
	 * mate-message-content for message rendering (from ChatMessage).
	 *
	 * Architecture: docs/architecture/docs-web-app.md
	 * Test: N/A — visual component, tested via E2E
	 */
	import { ReadOnlyMessage, text } from '@repo/ui';

	interface Props {
		/** Processed markdown (links fixed) to render via TipTap */
		content: string;
		/** Category is kept for API compatibility but not used for avatar (always shows OpenMates logo) */
		category: string;
	}

	let { content, category: _category }: Props = $props();
</script>

<div class="chat-history-content has-messages has-header">
	<div class="chat-message assistant docs-message">
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
	/* Reuse chat-history-content width-limiting from ChatHistory.svelte */
	.chat-history-content {
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

	/* --- GitHub code file links — styled like EmbedInlineLink (code app) --- */
	.docs-message :global(a[href*="github.com/glowingkitty/OpenMates/blob/"]) {
		display: inline;
		text-decoration: none;
		font-weight: 500;
		color: var(--color-app-code-start);
		transition: opacity 0.15s ease;
		cursor: pointer;
	}

	:global([data-theme="dark"]) .docs-message :global(a[href*="github.com/glowingkitty/OpenMates/blob/"]) {
		color: var(--color-app-code-end);
	}

	.docs-message :global(a[href*="github.com/glowingkitty/OpenMates/blob/"]:hover) {
		opacity: 0.8;
	}

	/* Small circular code-app badge before GitHub code links.
	   Matches EmbedInlineLink's 20px circular badge but CSS-only (no Svelte component). */
	.docs-message :global(a[href*="github.com/glowingkitty/OpenMates/blob/"]::before) {
		content: '';
		display: inline-block;
		width: 18px;
		height: 18px;
		min-width: 18px;
		border-radius: 50%;
		vertical-align: middle;
		margin-right: 3px;
		background: var(--color-app-code);
	}
</style>
