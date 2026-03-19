<!--
  Instagram Story Template — 1080x1920px vertical format.

  Full-height layout with brand header at top, large phone mockup center.

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import MockChatFeed from '../../components/MockChatFeed.svelte';
	import { loadScenario, loadTemplateConfig } from '../../data/loader';
	import type { MediaMessage } from '../../data/types';

	const config = loadTemplateConfig('instagram-story');
	const phoneConfig = config.phone!;

	let messages = $state<MediaMessage[]>([]);
	let ready = $state(false);

	onMount(() => {
		if (!browser) return;
		const params = new URL(window.location.href).searchParams;
		const scenarioId = params.get('scenario') || phoneConfig.scenario;

		try {
			messages = loadScenario(scenarioId).messages;
		} catch {
			messages = loadScenario('cuttlefish-chat').messages;
		}
		ready = true;
	});
</script>

<MediaCanvas width={config.width} height={config.height} {ready}>
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
				{#if messages.length > 0}
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
				{/if}
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
