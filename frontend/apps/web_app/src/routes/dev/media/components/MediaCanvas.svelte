<!--
  MediaCanvas — universal wrapper for media generation templates.

  Sets exact pixel dimensions, applies the dark gradient background,
  and exposes a .media-ready CSS class sentinel for Playwright to wait on.

  Usage:
    <MediaCanvas width={1200} height={630} ready={translationsReady}>
      {#snippet content()}
        ... template content ...
      {/snippet}
    </MediaCanvas>

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		width = 1200,
		height = 630,
		ready = false,
		background = 'gradient',
		borderRadius = 0,
		content
	}: {
		width?: number;
		height?: number;
		ready?: boolean;
		background?: 'gradient' | 'solid' | 'transparent';
		borderRadius?: number;
		content: Snippet;
	} = $props();

	let bgClass = $derived(
		background === 'gradient'
			? 'media-bg-gradient'
			: background === 'solid'
				? 'media-bg-solid'
				: 'media-bg-transparent'
	);
</script>

<div class="media-shell">
	<div
		class="media-canvas {bgClass}"
		class:media-ready={ready}
		style="width: {width}px; height: {height}px; border-radius: {borderRadius}px;"
	>
		{@render content()}
	</div>
</div>

<style>
	/* Intentional hardcoded: OG/media images are always dark-themed */
	:global(body) {
		margin: 0;
		padding: 0;
		background: #171717;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	.media-shell {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		min-height: 100dvh;
		background: #171717;
	}

	.media-canvas {
		position: relative;
		overflow: hidden;
		flex-shrink: 0;
	}

	.media-bg-gradient {
		background: linear-gradient(135deg, #1e1e2a 0%, #171720 100%);
	}

	.media-bg-solid {
		background: #171717;
	}

	.media-bg-transparent {
		background: transparent;
	}

	/* Blue decorative glow — top-left */
	.media-bg-gradient::before {
		content: '';
		position: absolute;
		top: -140px;
		left: -60px;
		width: 460px;
		height: 460px;
		border-radius: 50%;
		background: radial-gradient(circle, rgba(72, 103, 205, 0.14) 0%, transparent 70%);
		pointer-events: none;
	}

	/* Orange decorative glow — bottom-left */
	.media-bg-gradient::after {
		content: '';
		position: absolute;
		bottom: -80px;
		left: 80px;
		width: 320px;
		height: 320px;
		border-radius: 50%;
		background: radial-gradient(circle, rgba(255, 85, 59, 0.08) 0%, transparent 70%);
		pointer-events: none;
	}
</style>
