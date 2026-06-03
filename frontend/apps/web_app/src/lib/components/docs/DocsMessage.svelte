<script lang="ts">
	/**
	 * DocsMessage Component
	 *
	 * Renders documentation content styled as a single assistant chat message.
	 * Reuses the same classes as the regular chat: chat-history-content for
	 * width-limiting (from ChatHistory.svelte), and chat-message/mate-profile/
	 * mate-message-content for message rendering (from ChatMessage).
	 *
     * Post-processes rendered HTML to enhance Mermaid diagram blocks as
     * interactive SVGs, loading Mermaid only on pages that need it.
	 *
	 * Architecture: docs/architecture/frontend/docs-web-app.md
	 * Test: N/A — visual component, tested via E2E
	 */
	import { onMount } from 'svelte';
	import { text } from '@openmates/ui/src/i18n/translations';

	interface Props {
		/** Trusted HTML generated at build time from repository markdown */
		content: string;
		/** Category is kept for API compatibility but not used for avatar (always shows OpenMates logo) */
		category: string;
	}

	let { content, category: _category }: Props = $props();

	let messageContainer: HTMLElement;

	/**
	 * Post-process rendered HTML after mount:
	 * - Mermaid code blocks → rendered SVG diagrams, loaded only when needed.
	 */
	async function postProcessMermaidBlocks() {
		if (!messageContainer) return;

		const codeBlocks = messageContainer.querySelectorAll('pre code.language-mermaid');
		if (codeBlocks.length === 0) return;

		const mermaidModule = await import('mermaid');
		const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
		mermaidModule.default.initialize({
			startOnLoad: false,
			theme: isDark ? 'dark' : 'default',
			securityLevel: 'strict',
			fontFamily: 'var(--font-family-sans, system-ui, sans-serif)',
		});

		for (let i = 0; i < codeBlocks.length; i++) {
			const codeEl = codeBlocks[i] as HTMLElement;
			const block = codeEl.closest('pre');
			if (!block) continue;
			const codeText = codeEl.textContent || '';
			try {
					const mermaidId = `docs-mermaid-${i}`;
					const { svg } = await mermaidModule.default.render(mermaidId, codeText.trim());

					const wrapper = document.createElement('div');
					wrapper.className = 'docs-mermaid-diagram';
					wrapper.innerHTML = svg;
					block.replaceWith(wrapper);
			} catch (err) {
				console.warn('[DocsMessage] Mermaid render failed, keeping code block:', err);
			}
		}
	}

	onMount(() => {
		postProcessMermaidBlocks();
	});
</script>

<div class="chat-history-content has-messages has-header" data-testid="docs-content-scroll" bind:this={messageContainer}>
	<div class="chat-message assistant docs-message">
		<!-- OpenMates logo avatar — same as demo-for-everyone intro chat -->
		<div class="mate-profile openmates_official" style="animation: none; opacity: 1;"></div>

		<div class="message-align-left">
			<div class="mate-message-content" data-testid="mate-message-content" role="article">
				<div class="chat-mate-name">{$text('documentation.sender_name')}</div>
				<div class="chat-message-text">
					<!-- eslint-disable-next-line svelte/no-at-html-tags -- Generated from trusted repository markdown at build time. -->
					<div class="docs-rendered-content">{@html content}</div>
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

	/* --- Mermaid diagram styling --- */
	.docs-message :global(.docs-mermaid-diagram) {
		margin: 1rem 0;
		padding: 1.5rem;
		background: var(--color-grey-5, #fafafa);
		border: 1px solid var(--color-grey-20, #e5e7eb);
		border-radius: 12px;
		overflow-x: auto;
		text-align: center;
	}

	:global([data-theme="dark"]) .docs-message :global(.docs-mermaid-diagram) {
		background: var(--color-grey-10, #1a1a1a);
		border-color: var(--color-grey-25, #333);
	}

	.docs-message :global(.docs-mermaid-diagram svg) {
		max-width: 100%;
		height: auto;
	}

	.docs-rendered-content :global(pre) {
		margin: 0.9rem 0;
		padding: 1rem;
		border-radius: 10px;
		background: var(--color-grey-10);
		overflow-x: auto;
	}

	.docs-rendered-content :global(code) {
		font-family: var(--font-family-mono, monospace);
		font-size: 0.9em;
	}

	.docs-rendered-content :global(:not(pre) > code) {
		padding: 0.12rem 0.3rem;
		border-radius: 0.3rem;
		background: var(--color-grey-10);
	}

	.docs-rendered-content :global(img) {
		max-width: 100%;
		height: auto;
		border-radius: 10px;
	}

	.docs-rendered-content :global(table) {
		width: 100%;
		border-collapse: collapse;
		display: block;
		overflow-x: auto;
	}

	.docs-rendered-content :global(th),
	.docs-rendered-content :global(td) {
		border: 1px solid var(--color-grey-30);
		padding: 0.5rem 0.65rem;
		text-align: start;
	}
</style>
