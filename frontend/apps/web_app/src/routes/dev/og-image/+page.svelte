<!--
  OG Image Preview Page — /dev/og-image

  Renders a 1200×600px design card for screenshot-based OG image generation.
  Dark background. Left: slogan. Right: overlapping laptop + phone mockups,
  both with a browser/app chrome bar showing openmates.org.

  Architecture:
  - Lives under /dev/ so the existing +layout.svelte gate blocks it on production
  - Two iframes both pointing at /#chat-id=demo-for-everyone — real app, no mocking
  - Laptop: 1280×800 viewport. Iframe is offset left by sidebar width so the chat
    area (not the sidebar) is centred in the visible screen window.
  - Browser bar (CSS-only) sits inside the laptop bezel above the iframe.
  - Phone: 390×844 viewport with a minimal status-bar chrome strip.
  - The outer .og-canvas wrapper is exactly 1200×600px — Playwright clips to this.

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

	// ── Laptop mockup ──────────────────────────────────────────────────────────
	const LAPTOP_VIEWPORT_W = 1280; // full app viewport width
	const LAPTOP_VIEWPORT_H = 800;
	const LAPTOP_SCREEN_W = 480; // visible screen width inside bezel
	const LAPTOP_SCREEN_H = Math.round(LAPTOP_SCREEN_W * (LAPTOP_VIEWPORT_H / LAPTOP_VIEWPORT_W)); // 300px
	const LAPTOP_SCALE = LAPTOP_SCREEN_W / LAPTOP_VIEWPORT_W; // ≈ 0.375

	// The app sidebar is ~335px wide at 1280px viewport.
	// Shift the iframe left so the chat area (right of sidebar) fills the screen.
	// At scale 0.375: 335px sidebar becomes ~125px — shift iframe left to hide it.
	// We want the chat area centered, so offset by full sidebar width (unscaled).
	const SIDEBAR_W = 335; // px — app sidebar width at LAPTOP_VIEWPORT_W

	// Browser bar height (CSS-only chrome, sits inside the laptop lid above the screen)
	const BROWSER_BAR_H = 28; // px (rendered, not scaled)

	// Laptop chrome
	const LAPTOP_BEZEL_TOP = 10; // px — thin top bezel above browser bar
	const LAPTOP_BEZEL_SIDE = 10; // px — left/right bezel
	const LAPTOP_CHIN = 20; // px — bottom chin
	const LAPTOP_BASE_H = 16; // px — keyboard base
	// Outer lid dimensions
	const LAPTOP_LID_INNER_H = BROWSER_BAR_H + LAPTOP_SCREEN_H; // browser bar + screen
	const LAPTOP_LID_H = LAPTOP_BEZEL_TOP + LAPTOP_LID_INNER_H + LAPTOP_CHIN;
	const LAPTOP_OUTER_W = LAPTOP_SCREEN_W + LAPTOP_BEZEL_SIDE * 2;
	const LAPTOP_BASE_W = LAPTOP_OUTER_W + 48; // base wider than lid

	// ── Phone mockup ───────────────────────────────────────────────────────────
	const PHONE_VIEWPORT_W = 390;
	const PHONE_VIEWPORT_H = 844;
	const PHONE_SCREEN_H = 390; // visible screen height inside bezel
	const PHONE_SCREEN_W = Math.round(PHONE_SCREEN_H * (PHONE_VIEWPORT_W / PHONE_VIEWPORT_H)); // 180px
	const PHONE_SCALE = PHONE_SCREEN_H / PHONE_VIEWPORT_H; // ≈ 0.462

	// Phone chrome
	const PHONE_BEZEL_V = 14; // px top/bottom bezel
	const PHONE_BEZEL_H = 6; // px left/right bezel
	const PHONE_RADIUS = 26; // px corner radius
	const PHONE_OUTER_W = PHONE_SCREEN_W + PHONE_BEZEL_H * 2;
	const PHONE_OUTER_H = PHONE_BEZEL_V + PHONE_SCREEN_H + PHONE_BEZEL_V;

	// ── Load tracking ──────────────────────────────────────────────────────────
	let laptopLoaded = $state(false);
	let phoneLoaded = $state(false);
	let iframeLoaded = $derived(laptopLoaded && phoneLoaded);

	const iframeSrc = '/#chat-id=demo-for-everyone';

	function handleLaptopLoad() {
		setTimeout(() => {
			laptopLoaded = true;
		}, 3000);
	}
	function handlePhoneLoad() {
		setTimeout(() => {
			phoneLoaded = true;
		}, 3500);
	}

	onMount(() => {
		if (!browser) return;
		const t = setTimeout(() => {
			laptopLoaded = true;
			phoneLoaded = true;
		}, 10000);
		return () => clearTimeout(t);
	});
</script>

<div class="og-shell">
	<div class="og-canvas" class:og-ready={iframeLoaded}>
		<!-- ── LEFT: Slogan ───────────────────────────────────────────── -->
		<div class="og-left">
			<div class="og-logo">
				<img src="/favicon.svg" alt="OpenMates logo" class="og-logo-icon" />
				<span class="og-logo-name">OpenMates</span>
			</div>
			<h1 class="og-slogan">
				Digital team mates<br />
				<mark>for everyone</mark>
			</h1>
			<p class="og-tagline">Your AI mates that help with everyday life &amp; work</p>
		</div>

		<!-- ── RIGHT: Overlapping laptop + phone ──────────────────────── -->
		<div class="og-right">
			<!-- Laptop (behind, left) -->
			<div class="og-laptop" style="width: {LAPTOP_OUTER_W}px;">
				<!-- Lid -->
				<div
					class="og-laptop-lid"
					style="width: {LAPTOP_OUTER_W}px; height: {LAPTOP_LID_H}px; padding: {LAPTOP_BEZEL_TOP}px {LAPTOP_BEZEL_SIDE}px {LAPTOP_CHIN}px;"
				>
					<!-- Browser chrome bar (CSS-only, inside the bezel) -->
					<div
						class="og-browser-bar"
						style="height: {BROWSER_BAR_H}px; width: {LAPTOP_SCREEN_W}px;"
					>
						<!-- Traffic-light dots -->
						<div class="og-traffic-lights">
							<span class="og-dot og-dot-red"></span>
							<span class="og-dot og-dot-yellow"></span>
							<span class="og-dot og-dot-green"></span>
						</div>
						<!-- Address bar -->
						<div class="og-address-bar">
							<span class="og-lock">🔒</span>
							<span class="og-url">openmates.org</span>
						</div>
					</div>

					<!-- Screen (clips iframe) -->
					<div
						class="og-laptop-screen"
						style="width: {LAPTOP_SCREEN_W}px; height: {LAPTOP_SCREEN_H}px;"
					>
						<!--
							Offset the iframe left by SIDEBAR_W so the chat area
							(right of the sidebar) fills the visible screen window.
							The outer .og-laptop-screen clips the overflow.
						-->
						<iframe
							src={iframeSrc}
							title="OpenMates laptop preview"
							width={LAPTOP_VIEWPORT_W}
							height={LAPTOP_VIEWPORT_H}
							scrolling="no"
							style="
								transform: translateX(-{SIDEBAR_W}px) scale({LAPTOP_SCALE});
								transform-origin: top left;
								width: {LAPTOP_VIEWPORT_W}px;
								height: {LAPTOP_VIEWPORT_H}px;
							"
							onload={handleLaptopLoad}
						></iframe>
					</div>
				</div>

				<!-- Keyboard base -->
				<div class="og-laptop-base" style="height: {LAPTOP_BASE_H}px; width: {LAPTOP_BASE_W}px;">
					<div class="og-laptop-notch"></div>
				</div>
			</div>

			<!-- Phone (front, right, overlapping laptop) -->
			<div
				class="og-phone"
				style="width: {PHONE_OUTER_W}px; height: {PHONE_OUTER_H}px; border-radius: {PHONE_RADIUS}px;"
			>
				<!-- Top bezel -->
				<div class="og-phone-top" style="height: {PHONE_BEZEL_V}px;">
					<div class="og-phone-speaker"></div>
				</div>

				<!-- Screen -->
				<div class="og-phone-screen" style="width: {PHONE_SCREEN_W}px; height: {PHONE_SCREEN_H}px;">
					<iframe
						src={iframeSrc}
						title="OpenMates phone preview"
						width={PHONE_VIEWPORT_W}
						height={PHONE_VIEWPORT_H}
						scrolling="no"
						style="
							transform: scale({PHONE_SCALE});
							transform-origin: top left;
							width: {PHONE_VIEWPORT_W}px;
							height: {PHONE_VIEWPORT_H}px;
						"
						onload={handlePhoneLoad}
					></iframe>
				</div>

				<!-- Bottom bezel -->
				<div class="og-phone-bottom" style="height: {PHONE_BEZEL_V}px;">
					<div class="og-phone-home"></div>
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	/* ── Base ─────────────────────────────────────────────────────────────────── */
	:global(body) {
		margin: 0;
		padding: 0;
		/* Intentional hardcoded: app dark theme-color (#171717) */
		background: #171717;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	.og-shell {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		min-height: 100dvh;
		/* Intentional hardcoded: app dark theme background */
		background: #171717;
	}

	/* ── Canvas ────────────────────────────────────────────────────────────────── */
	.og-canvas {
		width: 1200px;
		height: 600px;
		display: flex;
		flex-direction: row;
		/* Intentional hardcoded: dark gradient matching app dark theme */
		background: linear-gradient(135deg, #1e1e2a 0%, #171720 100%);
		border-radius: 16px;
		overflow: hidden;
		position: relative;
		flex-shrink: 0;
	}

	/* Blue glow — intentional hardcoded brand blue, decorative */
	.og-canvas::before {
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

	/* Orange glow — intentional hardcoded brand orange, decorative */
	.og-canvas::after {
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

	/* ── Left: slogan ──────────────────────────────────────────────────────────── */
	.og-left {
		flex: 0 0 440px;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 60px 36px 60px 64px;
		position: relative;
		z-index: 1;
	}

	.og-logo {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 28px;
	}

	.og-logo-icon {
		width: 34px;
		height: 34px;
		flex-shrink: 0;
	}

	.og-logo-name {
		font-size: 1.125rem;
		font-weight: 600;
		/* Intentional hardcoded: brand blue lightened for dark bg */
		color: #7a9bf0;
		letter-spacing: -0.01em;
	}

	.og-slogan {
		font-size: 2.625rem;
		font-weight: 800;
		line-height: 1.15;
		letter-spacing: -0.03em;
		/* Intentional hardcoded: near-white text on dark bg for OG card */
		color: #f0f0f0;
		margin: 0 0 18px;
	}

	/* Gradient mark — matches HeroHeader/Login <mark> pattern */
	.og-slogan mark {
		background: linear-gradient(135deg, #4867cd 9.04%, #5a85eb 90.06%);
		/* Intentional vendor prefix: required for gradient text in WebKit */
		/* stylelint-disable-next-line property-no-vendor-prefix */
		-webkit-background-clip: text;
		background-clip: text;
		/* stylelint-disable-next-line property-no-vendor-prefix */
		-webkit-text-fill-color: transparent;
		background-color: transparent;
	}

	.og-tagline {
		font-size: 0.9375rem;
		line-height: 1.5;
		/* Intentional hardcoded: muted text on dark bg */
		color: #888;
		margin: 0;
		max-width: 320px;
	}

	/* ── Right: mockup stage ───────────────────────────────────────────────────── */
	.og-right {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: flex-start;
		padding: 20px 0;
		position: relative;
		z-index: 1;
		overflow: hidden;
	}

	/* ── Laptop ────────────────────────────────────────────────────────────────── */
	.og-laptop {
		display: flex;
		flex-direction: column;
		align-items: center;
		position: relative;
		flex-shrink: 0;
		/* Shift slightly left to give phone room to overlap on right */
		margin-left: -8px;
	}

	.og-laptop-lid {
		/* Intentional hardcoded: dark aluminium chrome */
		background: #252528;
		border-radius: 10px 10px 4px 4px;
		box-shadow:
			0 0 0 1px #3a3a40,
			0 20px 60px rgba(0, 0, 0, 0.6),
			0 4px 16px rgba(0, 0, 0, 0.4);
		box-sizing: border-box;
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
	}

	/* ── Browser bar ───────────────────────────────────────────────────────────── */
	.og-browser-bar {
		/* Intentional hardcoded: dark browser chrome, slightly lighter than lid */
		background: #2e2e32;
		border-radius: 2px 2px 0 0;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 8px;
		flex-shrink: 0;
		/* Subtle bottom border between bar and screen */
		border-bottom: 1px solid #3a3a3e;
	}

	.og-traffic-lights {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	/* macOS-style traffic light dots — intentional hardcoded system UI colors */
	.og-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		display: block;
		flex-shrink: 0;
	}

	.og-dot-red {
		background: #ff5f57;
	}
	.og-dot-yellow {
		background: #febc2e;
	}
	.og-dot-green {
		background: #28c840;
	}

	.og-address-bar {
		flex: 1;
		/* Intentional hardcoded: dark input field in browser chrome */
		background: #1e1e22;
		border-radius: 4px;
		height: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		padding: 0 6px;
		margin: 0 4px;
	}

	.og-lock {
		font-size: 0.5rem;
		line-height: 1;
		/* Intentional hardcoded: muted icon color in address bar */
		color: #666;
		flex-shrink: 0;
	}

	.og-url {
		font-size: 0.5625rem;
		font-weight: 500;
		/* Intentional hardcoded: address bar text on dark chrome */
		color: #ccc;
		letter-spacing: 0.01em;
		font-family: var(--font-primary, 'Lexend Deca Variable'), system-ui, sans-serif;
	}

	/* ── Laptop screen ─────────────────────────────────────────────────────────── */
	.og-laptop-screen {
		overflow: hidden;
		position: relative;
		/* Intentional hardcoded: dark screen bg before iframe loads */
		background: #111;
	}

	.og-laptop-screen iframe {
		border: none;
		display: block;
		pointer-events: none;
		/* translateX is set inline to shift past sidebar; scale set inline */
	}

	/* ── Laptop base ───────────────────────────────────────────────────────────── */
	.og-laptop-base {
		/* Intentional hardcoded: slightly lighter aluminium for base/keyboard area */
		background: linear-gradient(180deg, #2e2e32 0%, #252528 100%);
		border-radius: 0 0 6px 6px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 0;
	}

	.og-laptop-notch {
		width: 56px;
		height: 5px;
		/* Intentional hardcoded: hinge groove detail */
		background: #1a1a1c;
		border-radius: 0 0 4px 4px;
	}

	/* ── Phone ─────────────────────────────────────────────────────────────────── */
	.og-phone {
		display: flex;
		flex-direction: column;
		align-items: center;
		/* Intentional hardcoded: dark phone body */
		background: #1c1c1e;
		box-shadow:
			0 0 0 1px #3a3a3e,
			0 24px 64px rgba(0, 0, 0, 0.7),
			0 4px 16px rgba(0, 0, 0, 0.4);
		/* Overlap the laptop's right edge */
		margin-left: -72px;
		z-index: 2;
		flex-shrink: 0;
		position: relative;
	}

	.og-phone-top {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.og-phone-speaker {
		width: 38px;
		height: 3px;
		border-radius: 2px;
		/* Intentional hardcoded: speaker pill on phone top bezel */
		background: #3a3a3e;
	}

	.og-phone-screen {
		overflow: hidden;
		position: relative;
		/* Intentional hardcoded: dark screen bg before iframe loads */
		background: #111;
	}

	.og-phone-screen iframe {
		border: none;
		display: block;
		pointer-events: none;
	}

	.og-phone-bottom {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.og-phone-home {
		width: 60px;
		height: 3px;
		border-radius: 2px;
		/* Intentional hardcoded: home indicator pill */
		background: #444;
	}

	/* Playwright sentinel — no visual effect */
	.og-ready {
		/* Playwright waits for this class */
	}
</style>
