<!--
  OG Social Template — 1200x630px Open Graph image for Twitter/LinkedIn/Facebook.

  Same layout as og-github but with different default scenarios.
  Override via ?scenario= query parameter.

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import MediaCanvas from '../../components/MediaCanvas.svelte';
	import BrandHeader from '../../components/BrandHeader.svelte';
	import DevicePhone from '../../components/DevicePhone.svelte';
	import DeviceLaptop from '../../components/DeviceLaptop.svelte';
	import MockChatFeed from '../../components/MockChatFeed.svelte';
	import { loadScenario, loadTemplateConfig } from '../../data/loader';
	import type { MediaMessage } from '../../data/types';

	const config = loadTemplateConfig('og-social');
	const phoneConfig = config.phone!;
	const laptopConfig = config.laptop!;

	let phoneMessages = $state<MediaMessage[]>([]);
	let laptopMessages = $state<MediaMessage[]>([]);
	let ready = $state(false);

	onMount(() => {
		if (!browser) return;

		const params = new URL(window.location.href).searchParams;
		const phoneScenarioId = params.get('phone-scenario') || phoneConfig.scenario;
		const laptopScenarioId = params.get('laptop-scenario') || laptopConfig.scenario;

		try {
			phoneMessages = loadScenario(phoneScenarioId).messages;
			laptopMessages = loadScenario(laptopScenarioId).messages;
		} catch (e) {
			console.error('Failed to load scenario:', e);
			const fallback = loadScenario('cuttlefish-chat').messages;
			phoneMessages = fallback;
			laptopMessages = fallback;
		}

		ready = true;
	});
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
				{#if phoneMessages.length > 0}
					<div class="og-laptop-wrap">
						<DeviceLaptop
							screenWidth={laptopConfig.screen_width}
							screenHeight={laptopConfig.screen_height}
						>
							{#snippet screen()}
								<MockChatFeed
									messages={laptopMessages}
									scale={laptopConfig.scale}
									containerWidth={laptopConfig.screen_width}
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
								<MockChatFeed
									messages={phoneMessages}
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
