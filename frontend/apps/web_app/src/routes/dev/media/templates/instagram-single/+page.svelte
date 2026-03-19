<!--
  Instagram Single Post — 1080x1080px square format.

  Centered phone mockup with brand header above.

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

	const config = loadTemplateConfig('instagram-single');
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
