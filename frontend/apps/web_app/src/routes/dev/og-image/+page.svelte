<!--
  OG Image Preview Page — /dev/og-image
  
  Renders a 1200×600px design card for screenshot-based OG image generation.
  The card shows the app slogan on the left and the real web app (demo-for-everyone
  chat) embedded in a phone frame on the right.
  
  Architecture:
  - Lives under /dev/ so the existing +layout.svelte gate blocks it on production
  - Uses an iframe pointing at /#chat-id=demo-for-everyone so the phone frame always
    shows the real, current app design without any mocking
  - Phone viewport is 390×844px (iPhone 14 logical resolution) scaled down via CSS
    transform to fit the right half of the 1200×600 card
  - The outer .og-canvas wrapper is exactly 1200×600px — Playwright clips to this
  
  Usage (Playwright screenshot):
    await page.setViewportSize({ width: 1200, height: 600 })
    await page.goto('https://app.dev.openmates.org/dev/og-image')
    await page.waitForSelector('.og-ready')
    await page.screenshot({ path: 'og-image.png', clip: { x: 0, y: 0, width: 1200, height: 600 } })
  
  Docs: docs/architecture/web-app.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';

	// Phone frame dimensions (iPhone 14 logical resolution)
	const PHONE_WIDTH = 390;
	const PHONE_HEIGHT = 844;

	// Available height for phone inside the right half of the card
	// Right half = 600px wide, 600px tall, with 40px padding top/bottom
	// We scale to fit 580px height with room for a tiny bezel
	const TARGET_HEIGHT = 560;
	const SCALE = TARGET_HEIGHT / PHONE_HEIGHT; // ≈ 0.664
	const SCALED_WIDTH = Math.round(PHONE_WIDTH * SCALE); // ≈ 259px

	// Track when the iframe has loaded so Playwright knows when to screenshot
	let iframeLoaded = $state(false);
	let iframeEl = $state<HTMLIFrameElement | null>(null);

	// The iframe src — loads the real app with the public demo-for-everyone chat
	// Using a relative URL so it works on both localhost and app.dev.openmates.org
	const iframeSrc = '/#chat-id=demo-for-everyone';

	function handleIframeLoad() {
		// Small delay to let the app render its initial state (fonts, chat messages)
		setTimeout(() => {
			iframeLoaded = true;
		}, 3000);
	}

	onMount(() => {
		if (!browser) return;
		// Fallback: mark ready after 8 seconds even if load event doesn't fire
		const fallback = setTimeout(() => {
			iframeLoaded = true;
		}, 8000);
		return () => clearTimeout(fallback);
	});
</script>

<!--
  Outer shell: fills the viewport with a neutral background.
  The .og-canvas is the exact 1200×600 crop target.
-->
<div class="og-shell">
	<div class="og-canvas" class:og-ready={iframeLoaded}>
		<!-- LEFT HALF: Slogan -->
		<div class="og-left">
			<div class="og-logo">
				<img src="/favicon.svg" alt="OpenMates logo" class="og-logo-icon" />
				<span class="og-logo-name">OpenMates</span>
			</div>

			<h1 class="og-slogan">
				Digital team mates<br />
				<mark>for everyone</mark>
			</h1>

			<p class="og-tagline">Your AI mates that help with everyday life & work</p>
		</div>

		<!-- RIGHT HALF: Real app in a phone frame -->
		<div class="og-right">
			<div class="og-phone" style="width: {SCALED_WIDTH}px; height: {TARGET_HEIGHT}px;">
				<!-- Phone chrome: top bar with speaker cutout -->
				<div class="og-phone-top">
					<div class="og-phone-speaker"></div>
				</div>

				<!-- Iframe viewport — clipped to phone dimensions, scaled down from real dimensions -->
				<div class="og-phone-screen">
					<iframe
						bind:this={iframeEl}
						src={iframeSrc}
						title="OpenMates app preview"
						width={PHONE_WIDTH}
						height={PHONE_HEIGHT}
						scrolling="no"
						style="transform: scale({SCALE}); transform-origin: top left; width: {PHONE_WIDTH}px; height: {PHONE_HEIGHT}px;"
						onload={handleIframeLoad}
					></iframe>
				</div>

				<!-- Phone chrome: bottom home indicator -->
				<div class="og-phone-bottom">
					<div class="og-phone-home-indicator"></div>
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	/* Reset & base */
	:global(body) {
		margin: 0;
		padding: 0;
		background: var(--color-grey-20, #f3f3f3);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	/* Outer shell centers the canvas in the viewport */
	.og-shell {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		min-height: 100dvh;
		background: var(--color-grey-20, #f3f3f3);
		padding: 0;
	}

	/* The exact 1200×600px crop target */
	.og-canvas {
		width: 1200px;
		height: 600px;
		display: flex;
		flex-direction: row;
		/* Slightly off-white background with subtle gradient — on-brand and screenshot-friendly */
		background: linear-gradient(135deg, #f8f8fc 0%, #f0f2fb 100%);
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 8px 48px rgba(72, 103, 205, 0.12);
		position: relative;
		flex-shrink: 0;
	}

	/* Subtle decorative gradient blobs for visual depth */
	.og-canvas::before {
		content: '';
		position: absolute;
		top: -120px;
		left: -80px;
		width: 400px;
		height: 400px;
		border-radius: 50%;
		/* Brand blue — intentional hardcoded gradient, not a semantic color */
		background: radial-gradient(circle, rgba(72, 103, 205, 0.08) 0%, transparent 70%);
		pointer-events: none;
	}

	.og-canvas::after {
		content: '';
		position: absolute;
		bottom: -100px;
		left: 100px;
		width: 300px;
		height: 300px;
		border-radius: 50%;
		/* Brand orange accent — intentional hardcoded gradient */
		background: radial-gradient(circle, rgba(255, 85, 59, 0.06) 0%, transparent 70%);
		pointer-events: none;
	}

	/* ─── LEFT HALF ─────────────────────────────────────────────────── */
	.og-left {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 60px 50px 60px 64px;
		position: relative;
		z-index: 1;
	}

	.og-logo {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 32px;
	}

	.og-logo-icon {
		width: 36px;
		height: 36px;
		flex-shrink: 0;
	}

	.og-logo-name {
		font-size: 1.25rem;
		font-weight: 600;
		/* Brand blue — intentional, not semantic */
		color: #4867cd;
		letter-spacing: -0.01em;
	}

	.og-slogan {
		font-size: 2.75rem;
		font-weight: 800;
		line-height: 1.15;
		letter-spacing: -0.03em;
		color: var(--color-font-primary, #000);
		margin: 0 0 20px;
	}

	/* Brand gradient on "for everyone" — matches <mark> in HeroHeader and Login */
	.og-slogan mark {
		background: linear-gradient(135deg, #4867cd 9.04%, #5a85eb 90.06%);
		/* stylelint-disable-next-line property-no-vendor-prefix */
		-webkit-background-clip: text;
		background-clip: text;
		/* stylelint-disable-next-line property-no-vendor-prefix */
		-webkit-text-fill-color: transparent;
		/* Intentional raw color: brand primary gradient, not a semantic token */
		background-color: transparent;
	}

	.og-tagline {
		font-size: 1rem;
		line-height: 1.5;
		color: var(--color-font-tertiary, #6b6b6b);
		margin: 0;
		max-width: 340px;
	}

	/* ─── RIGHT HALF ─────────────────────────────────────────────────── */
	.og-right {
		width: 380px;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 20px 32px 20px 0;
		position: relative;
		z-index: 1;
	}

	/* Phone frame container */
	.og-phone {
		/* Dynamic width/height set inline via Svelte */
		border-radius: 28px;
		/* Intentional hardcoded dark chrome — standard phone mockup color */
		background: #1a1a1a;
		box-shadow:
			0 0 0 1.5px #333,
			0 24px 64px rgba(0, 0, 0, 0.35),
			0 4px 16px rgba(0, 0, 0, 0.2);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		position: relative;
	}

	/* Phone top bar with speaker */
	.og-phone-top {
		height: 22px;
		/* Same dark chrome as phone body */
		background: #1a1a1a;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		z-index: 2;
	}

	.og-phone-speaker {
		width: 48px;
		height: 4px;
		border-radius: 2px;
		/* Subtle notch — intentional hardcoded color, not semantic */
		background: #3a3a3a;
	}

	/* Phone screen area — clips the iframe to exact phone dimensions */
	.og-phone-screen {
		flex: 1;
		overflow: hidden;
		position: relative;
		background: var(--color-grey-0, #fff);
	}

	.og-phone-screen iframe {
		border: none;
		display: block;
		/* No pointer events — decorative only */
		pointer-events: none;
	}

	/* Phone bottom bar with home indicator */
	.og-phone-bottom {
		height: 20px;
		/* Same dark chrome as phone body */
		background: #1a1a1a;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		z-index: 2;
	}

	.og-phone-home-indicator {
		width: 80px;
		height: 3px;
		border-radius: 2px;
		/* Subtle home indicator — intentional hardcoded color, not semantic */
		background: #555;
	}

	/* Ready state indicator for Playwright — no visual effect */
	.og-ready {
		/* Playwright watches for this class before taking the screenshot */
	}
</style>
