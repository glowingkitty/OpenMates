<!--
  Instagram Single Post — 1080x1080px square format.

  Centered phone mockup with brand header above.
  Phone screen loads the real app via iframe in media mode.

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import DeviceIframe from '../../components/DeviceIframe.svelte';
	import { loadTemplateConfig } from '../../data/loader';

	const config = loadTemplateConfig('instagram-single');
	const phoneConfig = config.phone!;

	let phoneReady = $state(false);
</script>

<MediaCanvas width={config.width} height={config.height} ready={phoneReady}>
	{#snippet content()}
		<div class="ig-layout">
			<div class="ig-header">
				<BrandHeader
					headline={config.brand?.headline}
					subtitle={config.brand?.subtitle}
					headlineSize={config.brand?.headline_size || '2.25rem'}
					showFeatures={false}
				/>
			</div>

			<div class="ig-device">
				<DevicePhone
					screenWidth={phoneConfig.screen_width}
					screenHeight={phoneConfig.screen_height}
				>
					{#snippet screen()}
						<DeviceIframe
							src={phoneConfig.iframe_src || '/?media=1&seed=42&sidebar=closed'}
							width={phoneConfig.screen_width ?? 280}
							height={phoneConfig.screen_height ?? 560}
							scale={phoneConfig.scale ?? 0.55}
							onready={() => { phoneReady = true; }}
						/>
					{/snippet}
				</DevicePhone>
			</div>
		</div>
	{/snippet}
</MediaCanvas>

<style>
	.ig-layout {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		width: 100%;
		height: 100%;
		padding: 40px;
		box-sizing: border-box;
	}

	.ig-header {
		text-align: center;
		margin-bottom: 24px;
	}

	.ig-device {
		display: flex;
		justify-content: center;
	}
</style>
