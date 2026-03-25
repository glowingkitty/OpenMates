<!--
  Instagram Story Template — 1080x1920px vertical format.

  Full-height layout with brand header at top, large phone mockup center.
  Phone screen loads the real app via iframe in media mode.

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import DeviceIframe from '../../components/DeviceIframe.svelte';
	import { loadTemplateConfig } from '../../data/loader';

	const config = loadTemplateConfig('instagram-story');
	const phoneConfig = config.phone!;

	let phoneReady = $state(false);
</script>

<MediaCanvas width={config.width} height={config.height} ready={phoneReady}>
	{#snippet content()}
		<div class="story-layout">
			<div class="story-header">
				<BrandHeader
					headline={config.brand?.headline}
					subtitle={config.brand?.subtitle}
					headlineSize={config.brand?.headline_size || '2.5rem'}
					features={config.brand?.features}
					featureSize="1.125rem"
				/>
			</div>

			<div class="story-device">
				<DevicePhone
					screenWidth={phoneConfig.screen_width}
					screenHeight={phoneConfig.screen_height}
				>
					{#snippet screen()}
						<DeviceIframe
							src={phoneConfig.iframe_src || '/?media=1&seed=42&sidebar=closed'}
							width={phoneConfig.screen_width ?? 340}
							height={phoneConfig.screen_height ?? 680}
							scale={phoneConfig.scale ?? 0.6}
							onready={() => { phoneReady = true; }}
						/>
					{/snippet}
				</DevicePhone>
			</div>

			<div class="story-footer">
				<div class="story-swipe-hint">swipe up to try</div>
				<div class="story-url">openmates.org</div>
			</div>
		</div>
	{/snippet}
</MediaCanvas>

<style>
	.story-layout {
		display: flex;
		flex-direction: column;
		align-items: center;
		width: 100%;
		height: 100%;
		padding: 80px 60px 60px;
		box-sizing: border-box;
	}

	.story-header {
		text-align: center;
		margin-bottom: 40px;
	}

	.story-device {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.story-footer {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		margin-top: 40px;
	}

	.story-swipe-hint {
		font-size: 0.875rem;
		color: #888;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		font-weight: 600;
	}

	.story-url {
		font-size: 1.125rem;
		color: #7a9bf0;
		font-weight: 700;
	}
</style>
