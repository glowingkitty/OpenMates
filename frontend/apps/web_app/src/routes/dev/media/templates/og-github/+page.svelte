<!--
  OG GitHub Template — 1200x630px Open Graph image for GitHub repo and social sharing.

  Left side: Logo + headline + feature bullet points.
  Right side: Phone (front) + Laptop (behind, extending off-canvas right).

  Content is loaded from YAML scenario files for reproducibility.
  Screenshots are captured by Playwright using the .media-ready sentinel.

  Usage (Playwright):
    await page.setViewportSize({ width: 1200, height: 630 });
    await page.goto('/dev/media/templates/og-github');
    await page.waitForSelector('.media-ready');
    await page.screenshot({ path: 'og-github.png', clip: { x: 0, y: 0, width: 1200, height: 630 } });

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import DeviceLaptop from '../../components/DeviceLaptop.svelte';
	import MockChatFeed from '../../components/MockChatFeed.svelte';
	import { loadScenario, loadTemplateConfig } from '../../data/loader';
	import type { MediaMessage } from '../../data/types';

	// Load template config from YAML
	const config = loadTemplateConfig('og-github');
	const phoneConfig = config.phone!;
	const laptopConfig = config.laptop!;

	// Load scenario — can be overridden via ?scenario= query param
	let messages = $state<MediaMessage[]>([]);
	let ready = $state(false);

	onMount(() => {
		if (!browser) return;

		const params = new URL(window.location.href).searchParams;
		const scenarioId = params.get('scenario') || phoneConfig.scenario;

		try {
			const scenario = loadScenario(scenarioId);
			messages = scenario.messages;
		} catch (e) {
			console.error('Failed to load scenario:', e);
			// Fallback: load default scenario
			const scenario = loadScenario('cuttlefish-chat');
			messages = scenario.messages;
		}

		ready = true;
	});
</script>

<MediaCanvas width={config.width} height={config.height} {ready} borderRadius={16}>
	{#snippet content()}
		<div class="og-layout">
			<!-- Left: Brand info -->
			<div class="og-left">
				<BrandHeader
					headline={config.brand?.headline}
					subtitle={config.brand?.subtitle}
					features={config.brand?.features}
				/>
			</div>

			<!-- Right: Device mockups -->
			<div class="og-right">
				{#if messages.length > 0}
					<!-- Laptop (behind, partially off-canvas right) -->
					<div class="og-laptop-wrap">
						<DeviceLaptop
							screenWidth={laptopConfig.screen_width}
							screenHeight={laptopConfig.screen_height}
						>
							{#snippet screen()}
								<MockChatFeed
									{messages}
									scale={laptopConfig.scale}
									containerWidth={laptopConfig.screen_width}
								/>
							{/snippet}
						</DeviceLaptop>
					</div>

					<!-- Phone (front, overlapping laptop) -->
					<div class="og-phone-wrap">
						<DevicePhone
							screenWidth={phoneConfig.screen_width}
							screenHeight={phoneConfig.screen_height}
						>
							{#snippet screen()}
								<MockChatFeed
									{messages}
									scale={phoneConfig.scale}
									containerWidth={phoneConfig.screen_width}
								/>
							{/snippet}
						</DevicePhone>
					</div>
				{/if}
			</div>
		</div>
	{/snippet}
</MediaCanvas>

<style>
	.og-layout {
		display: flex;
		flex-direction: row;
		width: 100%;
		height: 100%;
	}

	.og-left {
		flex: 0 0 500px;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 50px 24px 50px 64px;
		position: relative;
		z-index: 1;
	}

	.og-right {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: flex-start;
		position: relative;
		z-index: 1;
		overflow: visible;
	}

	.og-laptop-wrap {
		position: absolute;
		right: -120px;
		top: 50%;
		transform: translateY(-50%);
		z-index: 1;
	}

	.og-phone-wrap {
		position: absolute;
		left: 0;
		top: 50%;
		transform: translateY(-50%);
		z-index: 2;
	}
</style>
