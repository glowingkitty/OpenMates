<!--
  DevicePhone — CSS-only phone device frame with a content slot.

  Renders a smartphone bezel (speaker pill, home indicator, rounded corners)
  around arbitrary content. Used in OG images, marketing graphics, etc.

  Usage:
    <DevicePhone screenWidth={220} screenHeight={430}>
      {#snippet screen()}
        <MockChatFeed ... />
      {/snippet}
    </DevicePhone>

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		screenWidth = 220,
		screenHeight = 430,
		bezelV = 14,
		bezelH = 8,
		radius = 30,
		screen
	}: {
		screenWidth?: number;
		screenHeight?: number;
		bezelV?: number;
		bezelH?: number;
		radius?: number;
		screen: Snippet;
	} = $props();

	let outerW = $derived(screenWidth + bezelH * 2);
	let outerH = $derived(bezelV + screenHeight + bezelV);
</script>

<div
	class="device-phone"
	style="width: {outerW}px; height: {outerH}px; border-radius: {radius}px;"
>
	<div class="device-phone-top" style="height: {bezelV}px;">
		<div class="device-phone-speaker"></div>
	</div>

	<div class="device-phone-screen" style="width: {screenWidth}px; height: {screenHeight}px;">
		{@render screen()}
	</div>

	<div class="device-phone-bottom" style="height: {bezelV}px;">
		<div class="device-phone-home"></div>
	</div>
</div>

<style>
	.device-phone {
		display: flex;
		flex-direction: column;
		align-items: center;
		/* Intentional hardcoded: dark phone body */
		background: #1c1c1e;
		box-shadow:
			0 0 0 1px #3a3a3e,
			0 24px 64px rgba(0, 0, 0, 0.7),
			0 4px 16px rgba(0, 0, 0, 0.4);
		flex-shrink: 0;
	}

	.device-phone-top {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.device-phone-speaker {
		width: 38px;
		height: 3px;
		border-radius: 2px;
		background: #3a3a3e;
	}

	.device-phone-screen {
		overflow: hidden;
		position: relative;
		background: #1a1a1a;
	}

	.device-phone-bottom {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.device-phone-home {
		width: 60px;
		height: 3px;
		border-radius: 2px;
		background: #444;
	}
</style>
