<!--
  DeviceIframe — Renders the real app inside an iframe for media/OG screenshot capture.

  Replaces MockAppScreen by loading the actual app at a given URL (e.g. /?media=1&seed=42)
  inside a scaled iframe. Same-origin iframes share auth cookies, so a logged-in Playwright
  session automatically authenticates the iframe content.

  The component watches for the .media-app-ready class on the iframe's document.body
  (emitted by +page.svelte in media mode) and calls onready() when detected.

  Usage:
    <DeviceIframe
      src="/?media=1&seed=42&sidebar=closed"
      width={220}
      height={430}
      scale={0.52}
      onready={() => { readyCount++ }}
    />

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import { onMount } from 'svelte';

	let {
		src,
		width,
		height,
		scale = 1,
		onready
	}: {
		src: string;
		width: number;
		height: number;
		scale?: number;
		onready?: () => void;
	} = $props();

	/** Natural (unscaled) dimensions — the iframe renders at full size, then CSS scales down */
	let naturalWidth = $derived(Math.round(width / scale));
	let naturalHeight = $derived(Math.round(height / scale));

	let iframeEl: HTMLIFrameElement | undefined = $state();
	let isReady = $state(false);

	onMount(() => {
		if (!iframeEl) return;

		const TIMEOUT_MS = 25000;
		let timeoutId: ReturnType<typeof setTimeout>;
		let observer: MutationObserver | undefined;

		function checkReady() {
			try {
				const body = iframeEl?.contentDocument?.body;
				if (body?.classList.contains('media-app-ready')) {
					markReady();
				}
			} catch {
				// Cross-origin — fall back to timeout
			}
		}

		function markReady() {
			if (isReady) return;
			isReady = true;
			cleanup();
			onready?.();
		}

		function cleanup() {
			if (timeoutId) clearTimeout(timeoutId);
			if (observer) observer.disconnect();
		}

		// Start observing once the iframe loads
		iframeEl.addEventListener('load', () => {
			try {
				const body = iframeEl?.contentDocument?.body;
				if (!body) {
					// Can't access — fall back to timeout
					return;
				}

				// Check if already ready (fast load)
				if (body.classList.contains('media-app-ready')) {
					markReady();
					return;
				}

				// Watch for the class to be added
				observer = new MutationObserver(() => {
					checkReady();
				});
				observer.observe(body, {
					attributes: true,
					attributeFilter: ['class']
				});
			} catch {
				// Cross-origin access denied — rely on timeout
			}
		});

		// Fallback timeout — mark ready even if signal never comes
		timeoutId = setTimeout(() => {
			console.warn(`[DeviceIframe] Timeout waiting for .media-app-ready on ${src}`);
			markReady();
		}, TIMEOUT_MS);

		return cleanup;
	});
</script>

<div
	class="device-iframe-container"
	style="width: {width}px; height: {height}px;"
>
	<iframe
		bind:this={iframeEl}
		{src}
		title="App preview"
		width={naturalWidth}
		height={naturalHeight}
		style="transform: scale({scale}); transform-origin: top left;"
		frameborder="0"
		scrolling="no"
	></iframe>
</div>

<style>
	.device-iframe-container {
		overflow: hidden;
		position: relative;
	}

	iframe {
		border: none;
		display: block;
	}
</style>
