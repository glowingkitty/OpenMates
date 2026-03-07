<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedPreviewLarge.svelte
  //
  // Purpose: Render [!](embed:ref) using existing embed-specific preview cards
  // (videos, images, code, websites, etc.) in an expanded "large" presentation.
  //
  // Architecture: reuses EmbedReferencePreview + UnifiedEmbedPreviewLarge wrapper,
  // with carousel behavior for consecutive large preview nodes.
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import { writable } from 'svelte/store';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import EmbedReferencePreview from './EmbedReferencePreview.svelte';
  import UnifiedEmbedPreviewLarge from './UnifiedEmbedPreviewLarge.svelte';

  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  interface Props {
    embedRef: string;
    embedId?: string | null;
    appId?: string | null;
    carouselIndex: number;
    carouselTotal: number;
  }

  let {
    embedRef,
    embedId = null,
    carouselIndex,
    carouselTotal,
  }: Props = $props();

  const carouselStateMap = new Map<string, ReturnType<typeof writable<number>>>();

  function getCarouselStore(runKey: string) {
    if (!carouselStateMap.has(runKey)) {
      carouselStateMap.set(runKey, writable(0));
    }
    return carouselStateMap.get(runKey)!;
  }

  let runKey = $derived(
    carouselIndex === 0 ? embedRef : `_run_${embedRef.replace(/-[a-zA-Z0-9]{3}$/, '')}_${carouselTotal}`,
  );
  let carouselStore = $derived(getCarouselStore(runKey));

  let currentIndex = $state(0);
  $effect(() => {
    const unsub = carouselStore.subscribe((value) => {
      currentIndex = value;
    });
    return unsub;
  });

  let isVisible = $derived(currentIndex === carouselIndex);
  let isFirstCard = $derived(carouselIndex === 0);
  let hasMultiple = $derived(carouselTotal > 1);
  let dotIndices = $derived(Array.from({ length: carouselTotal }, (_, i) => i));

  function handlePrevious(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    carouselStore.update((i) => (i - 1 + carouselTotal) % carouselTotal);
  }

  function handleNext(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    carouselStore.update((i) => (i + 1) % carouselTotal);
  }
</script>

{#if isVisible || isFirstCard}
  <div class="embed-preview-large-wrapper" class:embed-preview-large-wrapper--hidden={!isVisible}>
    <UnifiedEmbedPreviewLarge>
      <EmbedReferencePreview {embedRef} {embedId} variant="large" />
    </UnifiedEmbedPreviewLarge>

    {#if isFirstCard && hasMultiple}
      <button
        class="carousel-arrow carousel-arrow-left"
        type="button"
        onclick={handlePrevious}
        aria-label="Previous"
      >
        <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
      </button>

      <button
        class="carousel-arrow carousel-arrow-right"
        type="button"
        onclick={handleNext}
        aria-label="Next"
      >
        <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
      </button>

      <div class="embed-preview-large-dots" aria-hidden="true">
        {#each dotIndices as i}
          <span class="dot" class:dot--active={i === currentIndex}></span>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .embed-preview-large-wrapper {
    position: relative;
    width: 100%;
  }

  .embed-preview-large-wrapper--hidden {
    display: none;
  }

  .embed-preview-large-dots {
    display: flex;
    justify-content: center;
    gap: 5px;
    margin-top: 4px;
    margin-bottom: 2px;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-grey-40);
    transition: background 0.2s ease, transform 0.2s ease;
  }

  .dot--active {
    background: var(--color-font-primary);
    transform: scale(1.2);
  }

  .carousel-arrow {
    position: absolute;
    top: 8px;
    bottom: 26px;
    padding: 0 !important;
    min-width: unset !important;
    width: 40px !important;
    height: auto !important;
    border-radius: 0 !important;
    background-color: transparent !important;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background-color 0.15s ease;
    z-index: 20;
    pointer-events: auto;
  }

  .carousel-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .carousel-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .carousel-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .carousel-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important;
  }
</style>
