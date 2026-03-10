<!--
  OG Image Preview Page — /dev/og-image

  Renders a 1200×600px design card for screenshot-based OG image generation.
  Dark background (app dark theme color). Left: slogan. Right: laptop + phone
  mockups showing the real app (demo-for-everyone chat), overlapping each other.

  Architecture:
  - Lives under /dev/ so the existing +layout.svelte gate blocks it on production
  - Two iframes both pointing at /#chat-id=demo-for-everyone — real app, no mocking
  - Laptop frame: 1280×800 viewport scaled to fit ~520px wide
  - Phone frame: 390×844 viewport scaled to fit ~200px wide, overlapping the laptop
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

	// ── Laptop mockup dimensions ──────────────────────────────────────────────
	// Real viewport rendered inside the laptop screen
	const LAPTOP_VIEWPORT_W = 1280;
	const LAPTOP_VIEWPORT_H = 800;
	// Target rendered screen width inside the canvas right area
	const LAPTOP_SCREEN_W = 456; // px — the visible screen inside the bezel
	const LAPTOP_SCREEN_H = Math.round(LAPTOP_SCREEN_W * (LAPTOP_VIEWPORT_H / LAPTOP_VIEWPORT_W)); // 285px
	const LAPTOP_SCALE = LAPTOP_SCREEN_W / LAPTOP_VIEWPORT_W; // ≈ 0.356

	// ── Phone mockup dimensions ───────────────────────────────────────────────
	// iPhone 14 logical resolution
	const PHONE_VIEWPORT_W = 390;
	const PHONE_VIEWPORT_H = 844;
	// Target rendered screen height — phone should be ~70% of canvas height
	const PHONE_SCREEN_H = 380; // px — the visible screen inside the bezel
	const PHONE_SCREEN_W = Math.round(PHONE_SCREEN_H * (PHONE_VIEWPORT_W / PHONE_VIEWPORT_H)); // 175px
	const PHONE_SCALE = PHONE_SCREEN_H / PHONE_VIEWPORT_H; // ≈ 0.450

	// Laptop chrome sizes (bezel thickness)
	const LAPTOP_BEZEL = 14; // px — uniform bezel around screen
	const LAPTOP_CHIN = 28; // px — bottom chin (thicker)
	const LAPTOP_BASE_H = 18; // px — keyboard base strip height
	const LAPTOP_BASE_W = LAPTOP_SCREEN_W + LAPTOP_BEZEL * 2 + 60; // wider than lid
	// Total laptop lid height (bezel + screen + chin)
	const LAPTOP_LID_H = LAPTOP_BEZEL + LAPTOP_SCREEN_H + LAPTOP_CHIN;
	// Total laptop outer width
	const LAPTOP_OUTER_W = LAPTOP_SCREEN_W + LAPTOP_BEZEL * 2;

	// Phone chrome sizes
	const PHONE_BEZEL_V = 16; // px top/bottom bezel
	const PHONE_RADIUS = 24; // px — corner radius of phone body
	// Total phone outer height
	const PHONE_OUTER_H = PHONE_BEZEL_V + PHONE_SCREEN_H + PHONE_BEZEL_V;
	// Total phone outer width
	const PHONE_OUTER_W = PHONE_SCREEN_W + 12; // 6px bezel each side

	// ── Load tracking ─────────────────────────────────────────────────────────
	// Both iframes must load before we add .og-ready
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
		const fallback = setTimeout(() => {
			laptopLoaded = true;
			phoneLoaded = true;
		}, 10000);
		return () => clearTimeout(fallback);
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

		<!-- ── RIGHT: Overlapping laptop + phone ─────────────────────── -->
		<div class="og-right">
			<!-- Laptop mockup (behind, slightly left) -->
			<div class="og-laptop" style="width: {LAPTOP_OUTER_W}px;">
				<!-- Lid -->
				<div
					class="og-laptop-lid"
					style="
						width: {LAPTOP_OUTER_W}px;
						height: {LAPTOP_LID_H}px;
						padding: {LAPTOP_BEZEL}px {LAPTOP_BEZEL}px {LAPTOP_CHIN}px;
					"
				>
					<div
						class="og-laptop-screen"
						style="width: {LAPTOP_SCREEN_W}px; height: {LAPTOP_SCREEN_H}px;"
					>
						<iframe
							src={iframeSrc}
							title="OpenMates laptop preview"
							width={LAPTOP_VIEWPORT_W}
							height={LAPTOP_VIEWPORT_H}
							scrolling="no"
							style="
								transform: scale({LAPTOP_SCALE});
								transform-origin: top left;
								width: {LAPTOP_VIEWPORT_W}px;
								height: {LAPTOP_VIEWPORT_H}px;
							"
							onload={handleLaptopLoad}
						></iframe>
					</div>
				</div>
				<!-- Base / keyboard strip -->
				<div class="og-laptop-base" style="height: {LAPTOP_BASE_H}px; width: {LAPTOP_BASE_W}px;">
					<div class="og-laptop-notch"></div>
				</div>
			</div>

			<!-- Phone mockup (in front, slightly right + overlapping laptop) -->
			<div
				class="og-phone"
				style="
					width: {PHONE_OUTER_W}px;
					height: {PHONE_OUTER_H}px;
					border-radius: {PHONE_RADIUS}px;
				"
			>
				<!-- Top bezel with speaker pill -->
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

				<!-- Bottom bezel with home indicator -->
				<div class="og-phone-bottom" style="height: {PHONE_BEZEL_V}px;">
					<div class="og-phone-home"></div>
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	/* ── Base ──────────────────────────────────────────────────────────────── */
	:global(body) {
		margin: 0;
		padding: 0;
		/* Dark page bg — intentional hardcoded: matches app's own dark theme-color */
		background: #171717;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	/* Shell centers the canvas */
	.og-shell {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		min-height: 100dvh;
		/* Intentional hardcoded: app dark theme background (#171717) */
		background: #171717;
		padding: 0;
	}

	/* ── Canvas: exact 1200×600 crop target ──────────────────────────────── */
	.og-canvas {
		width: 1200px;
		height: 600px;
		display: flex;
		flex-direction: row;
		/* Dark gradient background — intentional hardcoded dark theme colors */
		background: linear-gradient(135deg, #1e1e2a 0%, #171720 100%);
		border-radius: 16px;
		overflow: hidden;
		position: relative;
		flex-shrink: 0;
	}

	/* Subtle blue glow top-left — decorative, intentional hardcoded brand blue */
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

	/* Subtle orange glow bottom-left — decorative, intentional hardcoded brand orange */
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

	/* ── Left: slogan ─────────────────────────────────────────────────────── */
	.og-left {
		flex: 0 0 460px;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 60px 40px 60px 64px;
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
		/* Brand blue on dark — intentional hardcoded */
		color: #7a9bf0;
		letter-spacing: -0.01em;
	}

	.og-slogan {
		font-size: 2.625rem;
		font-weight: 800;
		line-height: 1.15;
		letter-spacing: -0.03em;
		/* White text on dark — intentional hardcoded for the OG card dark bg */
		color: #f0f0f0;
		margin: 0 0 18px;
	}

	/* Brand gradient mark — matches HeroHeader/Login <mark> pattern */
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
		/* Muted white on dark — intentional hardcoded for the OG card dark bg */
		color: #888;
		margin: 0;
		max-width: 320px;
	}

	/* ── Right: mockup stage ──────────────────────────────────────────────── */
	.og-right {
		flex: 1;
		display: flex;
		align-items: center;
		/* Overlap: laptop a bit left, phone overlaps from the right */
		justify-content: flex-start;
		padding: 24px 0 24px 0;
		position: relative;
		z-index: 1;
		/* Clip anything that extends beyond the canvas */
		overflow: hidden;
	}

	/* ── Laptop mockup ────────────────────────────────────────────────────── */
	.og-laptop {
		display: flex;
		flex-direction: column;
		align-items: center;
		position: relative;
		/* Shift left so phone can overlap cleanly on the right */
		margin-left: -16px;
		flex-shrink: 0;
	}

	.og-laptop-lid {
		/* Intentional hardcoded: dark aluminium chrome for laptop mockup */
		background: #2a2a2e;
		border-radius: 10px 10px 4px 4px;
		box-shadow:
			0 0 0 1px #3a3a40,
			0 20px 60px rgba(0, 0, 0, 0.6),
			0 4px 16px rgba(0, 0, 0, 0.4);
		box-sizing: border-box;
		position: relative;
		z-index: 1;
	}

	.og-laptop-screen {
		overflow: hidden;
		position: relative;
		/* Intentional hardcoded: dark screen background before iframe loads */
		background: #111;
		border-radius: 2px;
	}

	.og-laptop-screen iframe {
		border: none;
		display: block;
		pointer-events: none;
	}

	.og-laptop-base {
		/* Intentional hardcoded: slightly lighter aluminium for keyboard base */
		background: linear-gradient(180deg, #323236 0%, #2a2a2e 100%);
		border-radius: 0 0 6px 6px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		position: relative;
		z-index: 0;
	}

	.og-laptop-notch {
		/* Hinge notch at the centre of the base */
		width: 60px;
		height: 6px;
		/* Intentional hardcoded: darker groove for hinge detail */
		background: #222;
		border-radius: 0 0 4px 4px;
	}

	/* ── Phone mockup ─────────────────────────────────────────────────────── */
	.og-phone {
		display: flex;
		flex-direction: column;
		align-items: center;
		/* Intentional hardcoded: dark phone body chrome */
		background: #1c1c1e;
		box-shadow:
			0 0 0 1px #3a3a3e,
			0 24px 64px rgba(0, 0, 0, 0.7),
			0 4px 16px rgba(0, 0, 0, 0.4);
		position: relative;
		/* Pull phone left to overlap the laptop's right edge */
		margin-left: -80px;
		/* Lift phone above laptop in z order */
		z-index: 2;
		flex-shrink: 0;
	}

	/* Top bezel */
	.og-phone-top {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.og-phone-speaker {
		width: 40px;
		height: 3px;
		border-radius: 2px;
		/* Intentional hardcoded: subtle pill detail on phone top bezel */
		background: #3a3a3e;
	}

	/* Screen */
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

	/* Bottom bezel */
	.og-phone-bottom {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.og-phone-home {
		width: 64px;
		height: 3px;
		border-radius: 2px;
		/* Intentional hardcoded: home-indicator pill */
		background: #444;
	}

	/* Playwright sentinel — no visual effect */
	.og-ready {
		/* Playwright waits for this class before screenshotting */
	}
</style>
