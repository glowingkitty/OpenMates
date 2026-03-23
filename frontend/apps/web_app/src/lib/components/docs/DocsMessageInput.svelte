<script lang="ts">
	/**
	 * DocsMessageInput — simplified message input for docs pages.
	 *
	 * When the user types a message and clicks send, it redirects to the
	 * main chat page with the message pre-filled via /#message= hash.
	 * A sessionStorage flag ('docs_auto_send') enables auto-send for
	 * same-origin navigations only.
	 *
	 * Architecture: docs/architecture/docs-web-app.md
	 */
	import { text } from '@repo/ui';
	import { page } from '$app/state';

	let message = $state('');
	let inputElement = $state<HTMLTextAreaElement | null>(null);

	/** Current docs page slug — included in the deep link for context */
	let currentSlug = $derived(page.url.pathname.replace('/docs/', '').replace('/docs', ''));

	function handleSend() {
		const trimmed = message.trim();
		if (!trimmed) return;

		// Set same-origin flag so the chat page knows to auto-send
		sessionStorage.setItem('docs_auto_send', 'true');

		// Include the docs context in the message for the AI
		const docsUrl = window.location.href;
		const contextMessage = `[Regarding: ${docsUrl}]\n\n${trimmed}`;

		// Redirect to main chat page with message in hash
		window.location.href = `/#message=${encodeURIComponent(contextMessage)}`;
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleSend();
		}
	}

	/** Auto-resize textarea to content */
	function handleInput() {
		if (!inputElement) return;
		inputElement.style.height = 'auto';
		inputElement.style.height = Math.min(inputElement.scrollHeight, 120) + 'px';
	}

	// Support inbound /#message= deep links on docs pages
	$effect(() => {
		if (typeof window === 'undefined') return;
		const hash = window.location.hash;
		if (hash.startsWith('#message=')) {
			const decoded = decodeURIComponent(hash.slice('#message='.length));
			message = decoded;
			// Clear the hash without triggering navigation
			history.replaceState(null, '', window.location.pathname + window.location.search);
		}
	});
</script>

<div class="docs-message-input">
	<div class="input-field">
		<textarea
			bind:this={inputElement}
			bind:value={message}
			placeholder={$text('documentation.actions.ask_question')}
			rows="1"
			onkeydown={handleKeydown}
			oninput={handleInput}
		></textarea>
		<button
			class="send-btn"
			disabled={!message.trim()}
			onclick={handleSend}
			title="Send"
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="22" y1="2" x2="11" y2="13" />
				<polygon points="22 2 15 22 11 13 2 9 22 2" />
			</svg>
		</button>
	</div>
</div>

<style>
	.docs-message-input {
		flex-shrink: 0;
		padding: 12px 16px;
		border-top: 1px solid var(--color-grey-30);
		background-color: var(--color-grey-20);
		border-radius: 0 0 17px 17px;
	}

	.input-field {
		display: flex;
		align-items: flex-end;
		gap: 8px;
		background-color: var(--color-grey-10);
		border-radius: 16px;
		padding: 8px 8px 8px 16px;
		border: 1px solid var(--color-grey-30);
		transition: border-color 0.15s ease;
	}

	.input-field:focus-within {
		border-color: var(--color-primary);
	}

	textarea {
		flex: 1;
		border: none;
		background: none;
		color: var(--color-font-primary);
		font-family: inherit;
		font-size: var(--font-size-p);
		line-height: 1.4;
		resize: none;
		outline: none;
		padding: 4px 0;
		min-height: 24px;
		max-height: 120px;
	}

	textarea::placeholder {
		color: var(--color-font-secondary);
	}

	.send-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border: none;
		border-radius: 12px;
		background-color: var(--color-primary);
		color: white;
		cursor: pointer;
		flex-shrink: 0;
		transition: all 0.15s ease;
	}

	.send-btn:hover:not(:disabled) {
		opacity: 0.9;
		transform: scale(1.05);
	}

	.send-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	/* Mobile adjustments */
	@media (max-width: 600px) {
		.docs-message-input {
			padding: 8px 12px;
		}

		.input-field {
			padding: 6px 6px 6px 12px;
		}

		.send-btn {
			width: 32px;
			height: 32px;
		}
	}

	/* Hide in print mode */
	@media print {
		.docs-message-input {
			display: none;
		}
	}
</style>
