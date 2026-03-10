<!--
  OG Image Preview Page — /dev/og-image

  Renders a 1200×600px design card for screenshot-based OG image generation.
  Dark background. Left: slogan. Right: overlapping laptop + phone mockups.

  Architecture:
  - Lives under /dev/ so the existing +layout.svelte gate blocks it on production
  - Laptop iframe → /?og=1: shows the new-chat welcome screen (daily inspiration
    banner + for-everyone card). ?og=1 skips the demo-for-everyone auto-redirect
    in +page.svelte and adds body.og-mode to hide dev UI (dev server label,
    report issue button).
  - Phone iframe → /#chat-id=demo-for-everyone: shows the for-everyone chat
    (same default behaviour as a real non-auth visitor).
  - Laptop: 1280×800 viewport. The iframe is scaled to fit LAPTOP_SCREEN_W wide
    and positioned so the chat area (past the sidebar) fills the clipping window.
    The iframe is position:absolute inside the overflow:hidden screen container.
    Left offset = -(SIDEBAR_W * LAPTOP_SCALE) to skip past the rendered sidebar.
  - Browser bar (CSS-only, macOS style) sits inside the laptop bezel above the screen.
  - Phone: 390×844 viewport scaled to fit PHONE_SCREEN_H tall.
  - The outer .og-canvas wrapper is exactly 1200×600px — Playwright clips to this.

  Transform math for laptop:
    LAPTOP_SCALE = LAPTOP_SCREEN_W / LAPTOP_VIEWPORT_W = 480 / 1280 = 0.375
    The iframe is scaled with transform-origin: top left → scaled width = 480px.
    To skip the ~335px sidebar in unscaled space, we shift left by
    SIDEBAR_W * LAPTOP_SCALE = 335 * 0.375 ≈ 126px in rendered space.
    iframe: position:absolute; left:-126px; transform:scale(0.375); transform-origin:top left
    The .og-laptop-screen clips to exactly LAPTOP_SCREEN_W × LAPTOP_SCREEN_H.

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
	const LAPTOP_VIEWPORT_W = 1280; // full app viewport width (px)
	const LAPTOP_VIEWPORT_H = 800;
	const LAPTOP_SCREEN_W = 480; // visible clipping window width inside bezel
	const LAPTOP_SCREEN_H = Math.round(LAPTOP_SCREEN_W * (LAPTOP_VIEWPORT_H / LAPTOP_VIEWPORT_W)); // 300px
	const LAPTOP_SCALE = LAPTOP_SCREEN_W / LAPTOP_VIEWPORT_W; // 0.375

	// The app sidebar is ~335px wide at 1280px viewport.
	// To skip it, shift the rendered iframe left by SIDEBAR_W * LAPTOP_SCALE in rendered space.
	// The .og-laptop-screen overflow:hidden then clips to show chat area from x=0.
	const SIDEBAR_W = 335; // px — sidebar width at LAPTOP_VIEWPORT_W
	const LAPTOP_IFRAME_LEFT = -(SIDEBAR_W * LAPTOP_SCALE); // ≈ -125.6px rendered

	// Browser chrome bar (CSS-only, sits inside laptop bezel above the screen)
	const BROWSER_BAR_H = 28; // px rendered

	// Laptop chrome dimensions
	const LAPTOP_BEZEL_TOP = 10;
	const LAPTOP_BEZEL_SIDE = 10;
	const LAPTOP_CHIN = 20;
	const LAPTOP_BASE_H = 16;
	const LAPTOP_LID_H = LAPTOP_BEZEL_TOP + BROWSER_BAR_H + LAPTOP_SCREEN_H + LAPTOP_CHIN;
	const LAPTOP_OUTER_W = LAPTOP_SCREEN_W + LAPTOP_BEZEL_SIDE * 2;
	const LAPTOP_BASE_W = LAPTOP_OUTER_W + 48;

	// ── Phone mockup ───────────────────────────────────────────────────────────
	const PHONE_VIEWPORT_W = 390;
	const PHONE_VIEWPORT_H = 844;
	const PHONE_SCREEN_H = 390; // visible clipping window height inside bezel
	const PHONE_SCREEN_W = Math.round(PHONE_SCREEN_H * (PHONE_VIEWPORT_W / PHONE_VIEWPORT_H)); // 180px
	const PHONE_SCALE = PHONE_SCREEN_H / PHONE_VIEWPORT_H; // ≈ 0.462

	// Phone chrome dimensions
	const PHONE_BEZEL_V = 14;
	const PHONE_BEZEL_H = 6;
	const PHONE_RADIUS = 26;
	const PHONE_OUTER_W = PHONE_SCREEN_W + PHONE_BEZEL_H * 2;
	const PHONE_OUTER_H = PHONE_BEZEL_V + PHONE_SCREEN_H + PHONE_BEZEL_V;

	// ── iframe sources ─────────────────────────────────────────────────────────
	// Laptop: welcome screen — ?og=1 skips demo-for-everyone redirect + hides dev UI
	const laptopSrc = '/?og=1';
	// Phone: for-everyone chat (default non-auth experience, same as real visitors)
	const phoneSrc = '/#chat-id=demo-for-everyone';

	// ── Load tracking ──────────────────────────────────────────────────────────
	let laptopLoaded = $state(false);
	let phoneLoaded = $state(false);
	let ogReady = $derived(laptopLoaded && phoneLoaded);

	function handleLaptopLoad() {
		// Extra delay for daily inspiration + welcome content to render
		setTimeout(() => {
			laptopLoaded = true;
		}, 3500);
	}
	function handlePhoneLoad() {
		setTimeout(() => {
			phoneLoaded = true;
		}, 3000);
	}

	onMount(() => {
		if (!browser) return;
		// Absolute fallback — mark ready even if iframes never fire onload
		const t = setTimeout(() => {
			laptopLoaded = true;
			phoneLoaded = true;
		}, 12000);
		return () => clearTimeout(t);
	});
</script>

<div class="og-shell">
	<div class="og-canvas" class:og-ready={ogReady}>
		<!-- ── LEFT: Slogan ─────────────────────────────────────────────── -->
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

		<!-- ── RIGHT: Overlapping laptop + phone ────────────────────────── -->
		<div class="og-right">
			<!-- Laptop (behind, slightly left) -->
			<div class="og-laptop" style="width: {LAPTOP_OUTER_W}px;">
				<!-- Lid -->
				<div
					class="og-laptop-lid"
					style="width: {LAPTOP_OUTER_W}px; height: {LAPTOP_LID_H}px; padding: {LAPTOP_BEZEL_TOP}px {LAPTOP_BEZEL_SIDE}px {LAPTOP_CHIN}px;"
				>
					<!-- CSS-only browser chrome bar (macOS style) -->
					<div
						class="og-browser-bar"
						style="height: {BROWSER_BAR_H}px; width: {LAPTOP_SCREEN_W}px;"
					>
						<div class="og-traffic-lights">
							<span class="og-dot og-dot-red"></span>
							<span class="og-dot og-dot-yellow"></span>
							<span class="og-dot og-dot-green"></span>
						</div>
						<div class="og-address-bar">
							<span class="og-lock">🔒</span>
							<span class="og-url">openmates.org</span>
						</div>
					</div>

					<!-- Screen: clips the scaled+offset iframe to show chat area only -->
					<div
						class="og-laptop-screen"
						style="width: {LAPTOP_SCREEN_W}px; height: {LAPTOP_SCREEN_H}px;"
					>
						<!--
							position:absolute lets us offset the iframe independent of its layout box.
							left = -(SIDEBAR_W * LAPTOP_SCALE) shifts the rendered content left so the
							chat area (past the sidebar) starts at the container's left edge.
							transform:scale() + transform-origin:top left scales from that shifted origin.
						-->
						<iframe
							src={laptopSrc}
							title="OpenMates laptop preview"
							scrolling="no"
							style="
								position: absolute;
								top: 0;
								left: {LAPTOP_IFRAME_LEFT}px;
								width: {LAPTOP_VIEWPORT_W}px;
								height: {LAPTOP_VIEWPORT_H}px;
								transform: scale({LAPTOP_SCALE});
								transform-origin: top left;
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
				<!-- Top bezel with speaker pill -->
				<div class="og-phone-top" style="height: {PHONE_BEZEL_V}px;">
					<div class="og-phone-speaker"></div>
				</div>

				<!-- Screen -->
				<div class="og-phone-screen" style="width: {PHONE_SCREEN_W}px; height: {PHONE_SCREEN_H}px;">
					<iframe
						src={phoneSrc}
						title="OpenMates phone preview"
						scrolling="no"
						style="
							position: absolute;
							top: 0;
							left: 0;
							width: {PHONE_VIEWPORT_W}px;
							height: {PHONE_VIEWPORT_H}px;
							transform: scale({PHONE_SCALE});
							transform-origin: top left;
						"
						onload={handlePhoneLoad}
					></iframe>
				</div>

				<!-- Bottom bezel with home indicator pill -->
				<div class="og-phone-bottom" style="height: {PHONE_BEZEL_V}px;">
					<div class="og-phone-home"></div>
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	/* ── Base ──────────────────────────────────────────────────────────────────── */
	:global(body) {
		margin: 0;
		padding: 0;
		/* Intentional hardcoded: matches app dark theme-color (#171717) */
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

	/* ── Canvas ─────────────────────────────────────────────────────────────────── */
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

	/* ── Left: slogan ───────────────────────────────────────────────────────────── */
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

	/* ── Right: mockup stage ────────────────────────────────────────────────────── */
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

	/* ── Laptop ─────────────────────────────────────────────────────────────────── */
	.og-laptop {
		display: flex;
		flex-direction: column;
		align-items: center;
		position: relative;
		flex-shrink: 0;
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

	/* ── Browser chrome bar ─────────────────────────────────────────────────────── */
	.og-browser-bar {
		/* Intentional hardcoded: dark browser chrome, slightly lighter than lid */
		background: #2e2e32;
		border-radius: 2px 2px 0 0;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 8px;
		flex-shrink: 0;
		border-bottom: 1px solid #3a3a3e;
	}

	.og-traffic-lights {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	/* macOS traffic light dots — intentional hardcoded system UI colors */
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
		/* Intentional hardcoded: dark URL input in browser chrome */
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
		/* Intentional hardcoded: muted lock icon in address bar */
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

	/* ── Laptop screen ──────────────────────────────────────────────────────────── */
	.og-laptop-screen {
		overflow: hidden;
		position: relative; /* establishes positioning context for the absolute iframe */
		/* Intentional hardcoded: dark fallback before iframe loads */
		background: #111;
	}

	.og-laptop-screen iframe {
		border: none;
		display: block;
		pointer-events: none;
		/* position/top/left/transform are all set inline */
	}

	/* ── Laptop base ────────────────────────────────────────────────────────────── */
	.og-laptop-base {
		/* Intentional hardcoded: aluminium keyboard base */
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

	/* ── Phone ──────────────────────────────────────────────────────────────────── */
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
		/* Intentional hardcoded: speaker pill on top bezel */
		background: #3a3a3e;
	}

	.og-phone-screen {
		overflow: hidden;
		position: relative; /* positioning context for the absolute iframe */
		/* Intentional hardcoded: dark fallback before iframe loads */
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

	/* Playwright sentinel — no visual effect, just a class Playwright waits for */
	.og-ready {
		/* intentional empty rule */
	}
</style>
