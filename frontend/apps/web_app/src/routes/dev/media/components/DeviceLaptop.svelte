<!--
  DeviceLaptop — CSS-only laptop device frame with browser chrome and content slot.

  Renders a laptop bezel with macOS-style traffic lights, address bar,
  keyboard base with hinge notch, around arbitrary content.

  Usage:
    <DeviceLaptop screenWidth={560} screenHeight={340}>
      {#snippet screen()}
        <MockChatFeed ... />
      {/snippet}
    </DeviceLaptop>

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		screenWidth = 560,
		screenHeight = 340,
		browserBarHeight = 24,
		bezelTop = 8,
		bezelSide = 8,
		chin = 14,
		baseHeight = 14,
		addressUrl = 'openmates.org',
		screen
	}: {
		screenWidth?: number;
		screenHeight?: number;
		browserBarHeight?: number;
		bezelTop?: number;
		bezelSide?: number;
		chin?: number;
		baseHeight?: number;
		addressUrl?: string;
		screen: Snippet;
	} = $props();

	let outerW = $derived(screenWidth + bezelSide * 2);
	let lidH = $derived(bezelTop + browserBarHeight + screenHeight + chin);
	let baseW = $derived(outerW + 48);
</script>

<div class="device-laptop" style="width: {outerW}px;">
	<div
		class="device-laptop-lid"
		style="width: {outerW}px; height: {lidH}px; padding: {bezelTop}px {bezelSide}px {chin}px;"
	>
		<!-- Browser chrome bar -->
		<div class="device-browser-bar" style="height: {browserBarHeight}px; width: {screenWidth}px;">
			<div class="device-traffic-lights">
				<span class="device-dot device-dot-red"></span>
				<span class="device-dot device-dot-yellow"></span>
				<span class="device-dot device-dot-green"></span>
			</div>
			<div class="device-address-bar">
				<span class="device-lock">&#x1F512;</span>
				<span class="device-url">{addressUrl}</span>
			</div>
		</div>

		<!-- Screen content -->
		<div class="device-laptop-screen" style="width: {screenWidth}px; height: {screenHeight}px;">
			{@render screen()}
		</div>
	</div>

	<!-- Keyboard base -->
	<div class="device-laptop-base" style="height: {baseHeight}px; width: {baseW}px;">
		<div class="device-laptop-notch"></div>
	</div>
</div>

<style>
	.device-laptop {
		display: flex;
		flex-direction: column;
		align-items: center;
		flex-shrink: 0;
	}

	.device-laptop-lid {
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

	.device-browser-bar {
		background: #2e2e32;
		border-radius: 2px 2px 0 0;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 8px;
		flex-shrink: 0;
		border-bottom: 1px solid #3a3a3e;
	}

	.device-traffic-lights {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.device-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		display: block;
		flex-shrink: 0;
	}
	.device-dot-red { background: #ff5f57; }
	.device-dot-yellow { background: #febc2e; }
	.device-dot-green { background: #28c840; }

	.device-address-bar {
		flex: 1;
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

	.device-lock {
		font-size: 0.4375rem;
		line-height: 1;
		color: #666;
		flex-shrink: 0;
	}

	.device-url {
		font-size: 0.5rem;
		font-weight: 500;
		color: #ccc;
		letter-spacing: 0.01em;
		font-family: var(--font-primary, 'Lexend Deca Variable'), system-ui, sans-serif;
	}

	.device-laptop-screen {
		overflow: hidden;
		position: relative;
		background: #1a1a1a;
	}

	.device-laptop-base {
		background: linear-gradient(180deg, #2e2e32 0%, #252528 100%);
		border-radius: 0 0 6px 6px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 0;
	}

	.device-laptop-notch {
		width: 48px;
		height: 4px;
		background: #1a1a1c;
		border-radius: 0 0 4px 4px;
	}
</style>
