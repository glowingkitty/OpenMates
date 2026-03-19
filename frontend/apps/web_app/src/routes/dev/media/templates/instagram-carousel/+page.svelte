<!--
  Instagram Carousel Template — 1080x1080px multi-slide format.

  Renders one slide at a time. Navigate slides via:
    - ?slide=N query parameter (1-indexed)
    - Arrow buttons in the preview
    - Playwright script iterates all slides automatically

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
	import type { MediaMessage, SlideConfig } from '../../data/types';

	const config = loadTemplateConfig('instagram-carousel');
	const slides = config.slides || [];

	let currentSlide = $state(0);
	let ready = $state(false);
	let scenarioCache = $state<Record<string, MediaMessage[]>>({});

	let slide = $derived(slides[currentSlide]);
	let totalSlides = $derived(slides.length);

	onMount(() => {
		if (!browser) return;

		const params = new URL(window.location.href).searchParams;
		const slideParam = params.get('slide');
		if (slideParam) {
			currentSlide = Math.max(0, Math.min(parseInt(slideParam) - 1, slides.length - 1));
		}

		// Pre-load all scenarios
		const scenarioIds = new Set(slides.filter(s => s.scenario).map(s => s.scenario!));
		for (const id of scenarioIds) {
			try {
				scenarioCache[id] = loadScenario(id).messages;
			} catch (e) {
				console.error(`Failed to load scenario ${id}:`, e);
			}
		}

		ready = true;
	});

	function goNext() {
		if (currentSlide < totalSlides - 1) currentSlide++;
	}

	function goPrev() {
		if (currentSlide > 0) currentSlide--;
	}
</script>

<MediaCanvas width={config.width} height={config.height} {ready}>
	{#snippet content()}
		{#if slide}
			<div class="carousel-slide">
				<!-- Slide counter -->
				<div class="slide-counter">{currentSlide + 1} / {totalSlides}</div>

				{#if slide.type === 'hero'}
					<div class="slide-hero">
						<BrandHeader
							headline={slide.headline || ''}
							subtitle={slide.subtitle || ''}
							headlineSize="2.5rem"
							showFeatures={false}
						/>
						{#if slide.scenario && scenarioCache[slide.scenario]}
							<div class="slide-device-center">
								<DevicePhone screenWidth={260} screenHeight={500}>
									{#snippet screen()}
										<MockChatFeed
											messages={scenarioCache[slide.scenario!]}
											scale={0.52}
											containerWidth={260}
										/>
									{/snippet}
								</DevicePhone>
							</div>
						{/if}
					</div>

				{:else if slide.type === 'chat'}
					<div class="slide-chat">
						<h2 class="slide-headline">{slide.headline || ''}</h2>
						{#if slide.scenario && scenarioCache[slide.scenario]}
							<div class="slide-device-center">
								{#if slide.device === 'laptop'}
									<DeviceLaptop screenWidth={480} screenHeight={300}>
										{#snippet screen()}
											<MockChatFeed
												messages={scenarioCache[slide.scenario!]}
												scale={0.5}
												containerWidth={480}
											/>
										{/snippet}
									</DeviceLaptop>
								{:else}
									<DevicePhone screenWidth={280} screenHeight={540}>
										{#snippet screen()}
											<MockChatFeed
												messages={scenarioCache[slide.scenario!]}
												scale={0.55}
												containerWidth={280}
											/>
										{/snippet}
									</DevicePhone>
								{/if}
							</div>
						{/if}
					</div>

				{:else if slide.type === 'feature'}
					<div class="slide-feature">
						<BrandHeader
							headline={slide.headline || ''}
							subtitle=""
							headlineSize="2.5rem"
							features={slide.features || []}
							featureSize="1.25rem"
						/>
					</div>

				{:else if slide.type === 'cta'}
					<div class="slide-cta">
						<img src="/favicon.svg" alt="OpenMates" class="cta-logo" />
						<h2 class="cta-headline">{slide.headline || ''}</h2>
						{#if slide.subtitle}
							<p class="cta-subtitle">{slide.subtitle}</p>
						{/if}
						{#if slide.cta_text}
							<div class="cta-button">{slide.cta_text}</div>
						{/if}
					</div>
				{/if}
			</div>
		{/if}

		<!-- Navigation (visible in browser preview, hidden in screenshot) -->
		<div class="carousel-nav">
			<button class="carousel-prev" onclick={goPrev} disabled={currentSlide === 0}>&#8592;</button>
			<button class="carousel-next" onclick={goNext} disabled={currentSlide === totalSlides - 1}>&#8594;</button>
		</div>
	{/snippet}
</MediaCanvas>

<style>
	.carousel-slide {
		width: 100%;
		height: 100%;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48px;
		box-sizing: border-box;
		position: relative;
	}

	.slide-counter {
		position: absolute;
		top: 20px;
		right: 24px;
		font-size: 0.875rem;
		color: #888;
		font-weight: 600;
		z-index: 10;
	}

	/* ── Hero slide ──────────────────── */
	.slide-hero {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 24px;
		text-align: center;
	}

	/* ── Chat slide ──────────────────── */
	.slide-chat {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 24px;
		width: 100%;
		height: 100%;
	}

	.slide-headline {
		font-size: 2rem;
		font-weight: 800;
		color: #f0f0f0;
		margin: 0;
		text-align: center;
	}

	.slide-device-center {
		display: flex;
		justify-content: center;
		flex: 1;
	}

	/* ── Feature slide ───────────────── */
	.slide-feature {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		width: 100%;
	}

	/* ── CTA slide ───────────────────── */
	.slide-cta {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 24px;
		text-align: center;
	}

	.cta-logo {
		width: 80px;
		height: 80px;
	}

	.cta-headline {
		font-size: 3rem;
		font-weight: 800;
		color: #f0f0f0;
		margin: 0;
	}

	.cta-subtitle {
		font-size: 1.5rem;
		color: #7a9bf0;
		margin: 0;
		font-weight: 600;
	}

	.cta-button {
		background: linear-gradient(135deg, #4867cd, #5a85eb);
		color: white;
		font-size: 1.25rem;
		font-weight: 700;
		padding: 16px 48px;
		border-radius: 12px;
		margin-top: 12px;
	}

	/* ── Navigation ──────────────────── */
	.carousel-nav {
		position: fixed;
		bottom: 20px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		gap: 12px;
		z-index: 100;
	}

	.carousel-nav button {
		background: rgba(255, 255, 255, 0.1);
		border: 1px solid rgba(255, 255, 255, 0.2);
		color: white;
		font-size: 1.25rem;
		padding: 8px 16px;
		border-radius: 8px;
		cursor: pointer;
	}

	.carousel-nav button:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.carousel-nav button:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.2);
	}
</style>
