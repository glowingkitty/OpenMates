<!--
  OG Social Template — 1200x630px Open Graph image for Twitter/LinkedIn/Facebook.

  Same layout as og-github but with different default seeds for varied content.
  Device screens load the real app via iframes in media mode (?media=1).

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import DeviceLaptop from '../../components/DeviceLaptop.svelte';
	import DeviceIframe from '../../components/DeviceIframe.svelte';
	import { loadTemplateConfig } from '../../data/loader';

	const config = loadTemplateConfig('og-social');
	const phoneConfig = config.phone!;
	const laptopConfig = config.laptop!;

	let phoneReady = $state(false);
	let laptopReady = $state(false);
	let ready = $derived(phoneReady && laptopReady);
</script>

<MediaCanvas width={config.width} height={config.height} {ready} borderRadius={16}>
	{#snippet content()}
		<div class="og-layout">
			<div class="og-left">
				<BrandHeader
					headline={config.brand?.headline}
					subtitle={config.brand?.subtitle}
					features={config.brand?.features}
				/>
			</div>

			<div class="og-right">
				<div class="og-laptop-wrap">
					<DeviceLaptop
						screenWidth={laptopConfig.screen_width}
						screenHeight={laptopConfig.screen_height}
					>
						{#snippet screen()}
							<DeviceIframe
								src={laptopConfig.iframe_src || '/?media=1&seed=99&sidebar=open'}
								width={laptopConfig.screen_width ?? 560}
								height={laptopConfig.screen_height ?? 340}
								scale={laptopConfig.scale ?? 0.58}
								onready={() => { laptopReady = true; }}
							/>
						{/snippet}
					</DeviceLaptop>
				</div>

				<div class="og-phone-wrap">
					<DevicePhone
						screenWidth={phoneConfig.screen_width}
						screenHeight={phoneConfig.screen_height}
					>
						{#snippet screen()}
							<DeviceIframe
								src={phoneConfig.iframe_src || '/?media=1&seed=99&sidebar=closed'}
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
