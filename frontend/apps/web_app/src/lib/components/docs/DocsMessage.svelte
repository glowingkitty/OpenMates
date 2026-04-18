<script lang="ts">
	/**
	 * DocsMessage Component
	 *
	 * Renders documentation content styled as a single assistant chat message.
	 * Reuses the same classes as the regular chat: chat-history-content for
	 * width-limiting (from ChatHistory.svelte), and chat-message/mate-profile/
	 * mate-message-content for message rendering (from ChatMessage).
	 *
	 * Post-processes TipTap-rendered DOM to:
	 * 1. Render Mermaid diagram blocks as interactive SVGs
	 * 2. Replace code blocks with CodeEmbedPreview/Fullscreen components
	 *
	 * Architecture: docs/architecture/frontend/docs-web-app.md
	 * Test: N/A — visual component, tested via E2E
	 */
	import { onMount, tick, mount, unmount } from 'svelte';
	import { ReadOnlyMessage, text } from '@repo/ui';
	import DocsCodeBlock from './DocsCodeBlock.svelte';

	interface Props {
		/** Processed markdown (links fixed) to render via TipTap */
		content: string;
		/** Category is kept for API compatibility but not used for avatar (always shows OpenMates logo) */
		category: string;
	}

	let { content, category: _category }: Props = $props();

	let messageContainer: HTMLElement;
	let mountedComponents: ReturnType<typeof mount>[] = [];

	/**
	 * Post-process TipTap DOM after render:
	 * - Mermaid code blocks → rendered SVG diagrams
	 * - Other code blocks → CodeEmbedPreview components
	 */
	async function postProcessCodeBlocks() {
		if (!messageContainer) return;

		// Wait for TipTap to finish rendering
		await tick();
		// Additional delay to ensure the lazy-loaded TipTap editor (IntersectionObserver) has mounted
		await new Promise(resolve => setTimeout(resolve, 300));

		const codeBlocks = messageContainer.querySelectorAll('.markdown-code-block');
		if (codeBlocks.length === 0) return;

		// Dynamically import mermaid only when needed (large dependency)
		let mermaidModule: typeof import('mermaid') | null = null;

		for (let i = 0; i < codeBlocks.length; i++) {
			const block = codeBlocks[i] as HTMLElement;
			const preEl = block.querySelector('pre');
			const codeEl = preEl?.querySelector('code');
			if (!codeEl) continue;

			const codeText = codeEl.textContent || '';

			// Detect language from TipTap's code block attributes or CSS class
			let language = '';
			const langClass = Array.from(codeEl.classList).find(c => c.startsWith('language-'));
			if (langClass) {
				language = langClass.replace('language-', '');
			}

			// Handle Mermaid blocks
			if (language === 'mermaid') {
				try {
					if (!mermaidModule) {
						mermaidModule = await import('mermaid');
						const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
						mermaidModule.default.initialize({
							startOnLoad: false,
							theme: isDark ? 'dark' : 'default',
							securityLevel: 'strict',
							fontFamily: 'var(--font-family-sans, system-ui, sans-serif)',
						});
					}

					const mermaidId = `docs-mermaid-${i}`;
					const { svg } = await mermaidModule.default.render(mermaidId, codeText.trim());

					const wrapper = document.createElement('div');
					wrapper.className = 'docs-mermaid-diagram';
					wrapper.innerHTML = svg;
					block.replaceWith(wrapper);
				} catch (err) {
					console.warn('[DocsMessage] Mermaid render failed, keeping code block:', err);
					// Leave the original code block visible on error
				}
				continue;
			}

			// Handle regular code blocks → mount CodeEmbedPreview
			const wrapper = document.createElement('div');
			wrapper.className = 'docs-code-block-wrapper';
			block.replaceWith(wrapper);

			const component = mount(DocsCodeBlock, {
				target: wrapper,
				props: {
					code: codeText,
					language,
					blockId: `docs-code-${i}`,
				},
			});
			mountedComponents.push(component);
		}
	}

	onMount(() => {
		postProcessCodeBlocks();

		return () => {
			// Cleanup mounted components
			for (const comp of mountedComponents) {
				try {
					unmount(comp);
				} catch {
					// Component may already be unmounted
				}
			}
			mountedComponents = [];
		};
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

	/* --- Code block wrapper — provides container query context for CodeEmbedPreview --- */
	.docs-message :global(.docs-code-block-wrapper) {
		margin: 0.75rem 0;
		min-width: 0;
	}
</style>
