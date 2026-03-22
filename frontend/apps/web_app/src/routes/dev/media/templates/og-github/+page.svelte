<!--
  OG GitHub Template — 1200x630px Open Graph image for GitHub repo and social sharing.

  Left side: Logo + headline + feature bullet points.
  Right side: Phone (front) + Laptop (behind, extending off-canvas right).

  Device screens load the REAL app via iframes in media mode (?media=1).
  The app renders with deterministic content (seeded suggestions, forced sidebar state)
  and emits .media-app-ready when painted. DeviceIframe detects this and signals ready
  to MediaCanvas, which sets .media-ready for Playwright capture.

  Usage (Playwright):
    await page.setViewportSize({ width: 1200, height: 630 });
    await page.goto('/dev/media/templates/og-github');
    await page.waitForSelector('.media-ready');
    await page.screenshot({ path: 'og-github.png', clip: { x: 0, y: 0, width: 1200, height: 630 } });

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import DeviceLaptop from '../../components/DeviceLaptop.svelte';
	import DeviceIframe from '../../components/DeviceIframe.svelte';
	import { loadTemplateConfig } from '../../data/loader';

	// Load template config from YAML
	const config = loadTemplateConfig('og-github');
	const phoneConfig = config.phone!;
	const laptopConfig = config.laptop!;

	// Track iframe ready states — MediaCanvas gets ready=true when ALL iframes report
	let phoneReady = $state(false);
	let laptopReady = $state(false);
	let ready = $derived(phoneReady && laptopReady);
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

			<!-- Right: Device mockups with real app iframes -->
			<div class="og-right">
				<!-- Laptop (behind, partially off-canvas right) -->
				<div class="og-laptop-wrap">
					<DeviceLaptop
						screenWidth={laptopConfig.screen_width}
						screenHeight={laptopConfig.screen_height}
					>
						{#snippet screen()}
							<DeviceIframe
								src={laptopConfig.iframe_src || '/?media=1&seed=42&sidebar=open'}
								width={laptopConfig.screen_width ?? 560}
								height={laptopConfig.screen_height ?? 340}
								scale={laptopConfig.scale ?? 0.58}
								onready={() => { laptopReady = true; }}
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
							<DeviceIframe
								src={phoneConfig.iframe_src || '/?media=1&seed=42&sidebar=closed'}
								width={phoneConfig.screen_width ?? 220}
								height={phoneConfig.screen_height ?? 430}
								scale={phoneConfig.scale ?? 0.52}
								onready={() => { phoneReady = true; }}
							/>
						{/snippet}
					</DevicePhone>
				</div>
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
