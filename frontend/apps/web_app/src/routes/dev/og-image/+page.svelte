<!--
  OG Image Preview Page — /dev/og-image

  Renders a 1200×630px design card for screenshot-based OG image generation.
  Dark background. Left: logo + headline + bullet points.
  Right: overlapping phone (front, center-right) + laptop (behind, extending off-canvas right).

  Architecture:
  - Lives under /dev/ so the existing +layout.svelte gate blocks it on production.
  - **No iframes.** Device mockups render real Svelte components (ChatMessage) directly
    with predefined mock data from ./mockData.ts. This makes the banner deterministic
    and independent of login state, IndexedDB, or server data.
  - The i18n system auto-initialises when @repo/ui is imported. We call
    waitForTranslations() to ensure translation strings are loaded before rendering.
  - The outer .og-canvas wrapper is exactly 1200×630px — Playwright clips to this.

  Usage (Playwright screenshot):
    await page.setViewportSize({ width: 1200, height: 630 })
    await page.goto('https://app.dev.openmates.org/dev/og-image')
    await page.waitForSelector('.og-ready')
    await page.screenshot({ path: 'og-image.png', clip: { x: 0, y: 0, width: 1200, height: 630 } })

  Docs: docs/architecture/web-app.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';

	// i18n auto-initialises when @repo/ui is imported
	import { ChatMessage, waitForTranslations, theme } from '@repo/ui';
	import { MOCK_CHAT_MESSAGES } from './mockData';

	// ── Phone mockup dimensions ───────────────────────────────────────────────
	// Phone screen shows ChatMessage components directly (no iframe).
	const PHONE_SCREEN_W = 220;
	const PHONE_SCREEN_H = 430;

	// Phone chrome dimensions
	const PHONE_BEZEL_V = 14;
	const PHONE_BEZEL_H = 8;
	const PHONE_RADIUS = 30;
	const PHONE_OUTER_W = PHONE_SCREEN_W + PHONE_BEZEL_H * 2;
	const PHONE_OUTER_H = PHONE_BEZEL_V + PHONE_SCREEN_H + PHONE_BEZEL_V;

	// ── Laptop mockup dimensions ──────────────────────────────────────────────
	// Laptop screen shows the same ChatMessage components at a larger scale.
	const LAPTOP_SCREEN_W = 560;
	const LAPTOP_SCREEN_H = 340;

	// Browser chrome bar (CSS-only, macOS style)
	const BROWSER_BAR_H = 24;

	// Laptop chrome dimensions
	const LAPTOP_BEZEL_TOP = 8;
	const LAPTOP_BEZEL_SIDE = 8;
	const LAPTOP_CHIN = 14;
	const LAPTOP_BASE_H = 14;
	const LAPTOP_LID_H = LAPTOP_BEZEL_TOP + BROWSER_BAR_H + LAPTOP_SCREEN_H + LAPTOP_CHIN;
	const LAPTOP_OUTER_W = LAPTOP_SCREEN_W + LAPTOP_BEZEL_SIDE * 2;
	const LAPTOP_BASE_W = LAPTOP_OUTER_W + 48;

	// ── Load tracking ──────────────────────────────────────────────────────────
	let translationsReady = $state(false);
	let ogReady = $derived(translationsReady);

	onMount(async () => {
		if (!browser) return;

		try {
			await waitForTranslations();
		} catch {
			// Translations may fail in isolation — proceed with fallback labels
		}

		// Force dark theme after a microtask delay. In Svelte, parent onMount
		// fires AFTER child onMount, so the root layout's initializeTheme()
		// overwrites any theme.set() we do here synchronously. Deferring with
		// setTimeout(0) ensures our dark theme set runs after all mount
		// callbacks and reactive effects have settled.
		setTimeout(() => {
			theme.set('dark');
			document.documentElement.setAttribute('data-theme', 'dark');
		}, 0);

		translationsReady = true;
	});
</script>

<div class="og-shell">
	<div class="og-canvas" class:og-ready={ogReady}>
		<!-- ── LEFT: Logo + Headline + Bullet points ───────────────────── -->
		<div class="og-left">
			<div class="og-logo">
				<img src="/favicon.svg" alt="OpenMates logo" class="og-logo-icon" />
				<span class="og-logo-name"><span class="og-logo-open">Open</span>Mates</span>
			</div>
			<h1 class="og-slogan">
				Digital team mates<br />
				<mark>For everyone.</mark>
			</h1>
			<ul class="og-features">
				<li><span class="og-check">&#x2714;</span> AI for everyday tasks &amp; learning</li>
				<li><span class="og-check">&#x2714;</span> Privacy focus</li>
				<li><span class="og-check">&#x2714;</span> No subscription</li>
				<li><span class="og-check">&#x2714;</span> Fair pay per use</li>
			</ul>
		</div>

		<!-- ── RIGHT: Phone (front) + Laptop (behind, extending off-canvas) ── -->
		<div class="og-right">
			<!-- Laptop (behind, partially off-canvas right) -->
			<div class="og-laptop" style="width: {LAPTOP_OUTER_W}px;">
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
							<span class="og-lock">&#x1F512;</span>
							<span class="og-url">openmates.org</span>
						</div>
					</div>

					<!-- Laptop screen: renders ChatMessage components directly -->
					<div
						class="og-laptop-screen"
						style="width: {LAPTOP_SCREEN_W}px; height: {LAPTOP_SCREEN_H}px;"
					>
						{#if translationsReady}
							<div class="og-chat-feed og-chat-feed-laptop">
								{#each MOCK_CHAT_MESSAGES as msg}
									<ChatMessage
										role={msg.role}
										content={msg.content}
										category={msg.category}
										containerWidth={LAPTOP_SCREEN_W}
									/>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				<!-- Keyboard base -->
				<div class="og-laptop-base" style="height: {LAPTOP_BASE_H}px; width: {LAPTOP_BASE_W}px;">
					<div class="og-laptop-notch"></div>
				</div>
			</div>

			<!-- Phone (front, overlapping laptop) -->
			<div
				class="og-phone"
				style="width: {PHONE_OUTER_W}px; height: {PHONE_OUTER_H}px; border-radius: {PHONE_RADIUS}px;"
			>
				<!-- Top bezel with speaker pill -->
				<div class="og-phone-top" style="height: {PHONE_BEZEL_V}px;">
					<div class="og-phone-speaker"></div>
				</div>

				<!-- Phone screen: renders ChatMessage components directly -->
				<div class="og-phone-screen" style="width: {PHONE_SCREEN_W}px; height: {PHONE_SCREEN_H}px;">
					{#if translationsReady}
						<div class="og-chat-feed og-chat-feed-phone">
							{#each MOCK_CHAT_MESSAGES as msg}
								<ChatMessage
									role={msg.role}
									content={msg.content}
									category={msg.category}
									containerWidth={PHONE_SCREEN_W}
								/>
							{/each}
						</div>
					{/if}
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
		height: 630px;
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

	/* ── Left: Logo + Headline + Bullet points ─────────────────────────────────── */
	.og-left {
		flex: 0 0 500px;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 50px 24px 50px 64px;
		position: relative;
		z-index: 1;
	}

	.og-logo {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 24px;
	}

	.og-logo-icon {
		width: 40px;
		height: 40px;
		flex-shrink: 0;
	}

	.og-logo-name {
		font-size: 1.375rem;
		font-weight: 700;
		/* Intentional hardcoded: near-white on dark bg */
		color: #f0f0f0;
		letter-spacing: -0.01em;
	}

	.og-logo-open {
		/* Intentional hardcoded: brand blue for "Open" in "OpenMates" */
		color: #7a9bf0;
	}

	.og-slogan {
		font-size: 2.75rem;
		font-weight: 800;
		line-height: 1.15;
		letter-spacing: -0.03em;
		/* Intentional hardcoded: near-white text on dark bg for OG card */
		color: #f0f0f0;
		margin: 0 0 28px;
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

	/* ── Feature bullet points ─────────────────────────────────────────────────── */
	.og-features {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.og-features li {
		font-size: 1.125rem;
		font-weight: 500;
		/* Intentional hardcoded: near-white text on dark bg */
		color: #e0e0e0;
		display: flex;
		align-items: center;
		gap: 12px;
		line-height: 1.3;
	}

	.og-check {
		/* Intentional hardcoded: green checkmark matching reference design */
		color: #28c840;
		font-size: 1.25rem;
		flex-shrink: 0;
		line-height: 1;
	}

	/* ── Right: mockup stage ────────────────────────────────────────────────────── */
	.og-right {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: flex-start;
		padding: 0;
		position: relative;
		z-index: 1;
		overflow: visible;
	}

	/* ── Chat feed (rendered inside device screens) ─────────────────────────────── */
	.og-chat-feed {
		display: flex;
		flex-direction: column;
		gap: 0;
		padding: 8px 4px;
		overflow: hidden;
		height: 100%;
		pointer-events: none;
	}

	/* Scale down the real ChatMessage components to fit mockup screens.
	   The components render at their natural size; CSS transform shrinks them
	   to fit inside the device bezel. */
	.og-chat-feed-phone {
		transform: scale(0.52);
		transform-origin: top left;
		width: 192.3%; /* 100% / 0.52 — fill phone screen width in unscaled space */
	}

	.og-chat-feed-laptop {
		transform: scale(0.58);
		transform-origin: top left;
		width: 172.4%; /* 100% / 0.58 — fill laptop screen width in unscaled space */
	}

	/* Override ChatMessage styles inside the OG banner to look correct at small scale.
	   These are intentional hardcoded overrides for the OG image context only. */
	.og-chat-feed :global(.chat-message) {
		/* Remove large bottom margins from the real component */
		margin-bottom: 4px !important;
	}

	.og-chat-feed :global(.mate-profile) {
		/* Shrink the mate profile avatar for the mockup */
		width: 32px !important;
		height: 32px !important;
		margin: 4px !important;
	}

	.og-chat-feed :global(.mate-profile::after),
	.og-chat-feed :global(.mate-profile::before) {
		/* Hide the AI badge at this scale — too small to be legible */
		display: none !important;
	}

	/* ── Laptop ─────────────────────────────────────────────────────────────────── */
	.og-laptop {
		display: flex;
		flex-direction: column;
		align-items: center;
		position: absolute;
		/* Position laptop behind phone, extending off right edge of canvas */
		right: -120px;
		top: 50%;
		transform: translateY(-50%);
		z-index: 1;
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
		gap: 6px;
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
		width: 7px;
		height: 7px;
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
		height: 14px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		padding: 0 6px;
		margin: 0 4px;
	}

	.og-lock {
		font-size: 0.4375rem;
		line-height: 1;
		/* Intentional hardcoded: muted lock icon in address bar */
		color: #666;
		flex-shrink: 0;
	}

	.og-url {
		font-size: 0.5rem;
		font-weight: 500;
		/* Intentional hardcoded: address bar text on dark chrome */
		color: #ccc;
		letter-spacing: 0.01em;
		font-family: var(--font-primary, 'Lexend Deca Variable'), system-ui, sans-serif;
	}

	/* ── Laptop screen ──────────────────────────────────────────────────────────── */
	.og-laptop-screen {
		overflow: hidden;
		position: relative;
		/* Intentional hardcoded: dark app background matching the chat area */
		background: #1a1a1a;
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
		width: 48px;
		height: 4px;
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
		z-index: 2;
		flex-shrink: 0;
		position: absolute;
		/* Position phone in front, center-right area */
		left: 0;
		top: 50%;
		transform: translateY(-50%);
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
		position: relative;
		/* Intentional hardcoded: dark app background matching the chat area */
		background: #1a1a1a;
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
</style>
