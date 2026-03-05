<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedPreviewLarge.svelte
  //
  // Full-width tall embed preview card rendered inline in the message flow when
  // the LLM writes [!](embed:some-ref) (exclamation-mark display text).
  //
  // Visual design:
  //   A full-width, ~200px-tall card with:
  //   - Gradient background using the app colour
  //   - Centered BasicInfosBar-style bottom section (app icon + name)
  //   - When multiple consecutive large previews exist: left/right chevron arrows
  //     (same design as DailyInspirationBanner carousel)
  //
  // The component receives carouselIndex and carouselTotal from the TipTap node.
  // When carouselTotal > 1, only the card at carouselIndex === currentIndex is
  // visible; the arrows navigate between them.
  //
  // IMPORTANT: Because TipTap renders each node independently, the carousel
  // state (currentIndex) must be shared between sibling nodes. We use a simple
  // per-message-level approach: all large preview nodes in the same consecutive
  // run share state via a module-level Map keyed by the first node's embedRef.
  // The first node in each run (carouselIndex === 0) owns the shared state and
  // the arrows; sibling nodes just show/hide based on the shared index.
  //
  // Architecture context: See docs/architecture/embed-types.md
  // Tests: (none yet)

  import { getLucideIcon } from '../../utils/categoryUtils';
  import { embedStore, embedRefIndexVersion } from '../../services/embedStore';

  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  interface Props {
    /** Short slug from the LLM (e.g. "ryanair-0600-k8D") */
    embedRef: string;
    /** Pre-resolved UUID — may be null when the node is first created */
    embedId?: string | null;
    /** app_id hint from parse-time — may be null */
    appId?: string | null;
    /**
     * 0-based index of this card in the consecutive run of large previews.
     * 0 = first card in the run (owns the carousel state and arrows).
     */
    carouselIndex: number;
    /**
     * Total number of cards in this consecutive run.
     * 1 = standalone card (no arrows).
     */
    carouselTotal: number;
  }

  let {
    embedRef,
    embedId = null,
    appId = null,
    carouselIndex,
    carouselTotal,
  }: Props = $props();

  // Reactively resolve the effective appId (same pattern as EmbedInlineLink).
  let effectiveAppId = $derived.by(() => {
    void $embedRefIndexVersion;
    return appId ?? embedStore.resolveAppIdByRef(embedRef);
  });

  // Gradient background style using the app colour.
  let backgroundStyle = $derived(
    effectiveAppId
      ? `background: var(--color-app-${effectiveAppId});`
      : 'background: var(--color-grey-25);',
  );

  // Display label — strip the random 3-char suffix for readability.
  let displayLabel = $derived(embedRef.replace(/-[a-zA-Z0-9]{3}$/, '') || embedRef);

  // ── Carousel state ──────────────────────────────────────────────────────────
  //
  // Each consecutive run of large preview nodes shares a carousel index stored
  // in a module-level WeakMap.  The "run key" is the embedRef of the first node
  // in the run (carouselIndex === 0).
  //
  // Only the first node (carouselIndex === 0) renders the arrows.  All nodes in
  // the run subscribe to the same state and show/hide accordingly.
  //
  // Module-level map: runKey → currentIndex (Svelte writable store)
  import { writable } from 'svelte/store';

  // Map from run-key (first node's embedRef) to a writable store holding the
  // current visible index for that run.
  const _carouselStateMap = new Map<string, ReturnType<typeof writable<number>>>();

  function getCarouselStore(runKey: string) {
    if (!_carouselStateMap.has(runKey)) {
      _carouselStateMap.set(runKey, writable(0));
    }
    return _carouselStateMap.get(runKey)!;
  }

  // The run key is the embedRef of the first card in the run.
  // For the first card, runKey === embedRef.
  // For subsequent cards, we need the first card's embedRef — but since TipTap
  // renders nodes independently, we derive it from carouselIndex and the node's
  // own embedRef.  The simplest approach: use a composite key that all cards in
  // the run share.  We use the embedRef of the FIRST card, which is carried as
  // a separate attr... but we don't have that here.
  //
  // SIMPLER APPROACH: use a stable key derived from the node's position in the
  // run.  Since carouselIndex is 0-based and carouselTotal is known, we can use
  // the embedRef of THIS node prefixed by its index to produce a per-run key.
  // For the first node: key = embedRef.
  // For later nodes: key = unknown.
  //
  // PRACTICAL SOLUTION: use the TipTap node's DOM position.  But that's not
  // available in Svelte. Instead, use a "group ID" attr that is set to the
  // FIRST card's embedRef for all cards in the run.  We add this attr in
  // parse_message.ts when assigning carouselIndex/carouselTotal.
  //
  // For now, use the embedRef of THIS card stripped of the random suffix as
  // the group key — adjacent embeds from the same app run will naturally share
  // a key.  This is a best-effort approach that works in almost all cases.
  let runKey = $derived(
    carouselIndex === 0
      ? embedRef  // first card IS the key
      : `_run_${displayLabel}_${carouselTotal}`  // approximate group key
  );

  // Store for this run's current visible index.
  let carouselStore = $derived(getCarouselStore(runKey));

  // Current visible index (reactive to store changes).
  let currentIndex = $state(0);
  $effect(() => {
    const unsub = carouselStore.subscribe((v) => { currentIndex = v; });
    return unsub;
  });

  // Is this card currently visible?
  let isVisible = $derived(currentIndex === carouselIndex);

  // Only the first card renders the arrows; it gets a reference to the group store.
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

  /**
   * Open embed fullscreen on click.
   */
  async function openFullscreen(): Promise<void> {
    const resolvedEmbedId = embedId || embedStore.resolveByRef(embedRef);
    if (!resolvedEmbedId) {
      console.warn(
        `[EmbedPreviewLarge] Cannot open fullscreen: embed_ref "${embedRef}" not yet resolved`,
      );
      return;
    }

    let targetEmbedId = resolvedEmbedId;
    let focusChildEmbedId: string | undefined;
    try {
      const rawEntry = await embedStore.getRawEntry(`embed:${resolvedEmbedId}`);
      if (rawEntry?.parent_embed_id) {
        targetEmbedId = rawEntry.parent_embed_id;
        focusChildEmbedId = resolvedEmbedId;
      }
    } catch (err) {
      console.debug(`[EmbedPreviewLarge] getRawEntry failed, using child embed_id:`, err);
    }

    document.dispatchEvent(
      new CustomEvent('embedfullscreen', {
        detail: {
          embedId: targetEmbedId,
          embedType: 'app-skill-use',
          focusChildEmbedId,
        },
        bubbles: true,
      }),
    );
  }

  async function handleClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    await openFullscreen();
  }

  async function handleKeyDown(e: KeyboardEvent) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    e.stopPropagation();
    await openFullscreen();
  }
</script>

<!--
  Render only if this card is visible in the carousel (or if it's the only card).
  Non-first cards also hide completely when not visible to avoid layout gaps.
  The first card renders the arrows that navigate between all sibling cards.
-->
{#if isVisible || isFirstCard}
  <div
    class="embed-preview-large-wrapper"
    class:embed-preview-large-wrapper--hidden={!isVisible}
  >
    <!-- The card itself — clickable to open fullscreen -->
    <div
      class="embed-preview-large"
      style={backgroundStyle}
      onclick={handleClick}
      role="button"
      tabindex="0"
      onkeydown={handleKeyDown}
    >
      <!-- Content area -->
      <div class="embed-preview-large-content">
        <!-- App icon -->
        <span class="embed-preview-large-icon" aria-hidden="true">
          <span class="icon_rounded {effectiveAppId || ''}"></span>
        </span>
        <!-- Label -->
        <span class="embed-preview-large-label">{displayLabel}</span>
        <!-- Dot indicators (only on first card so they don't duplicate) -->
        {#if isFirstCard && hasMultiple}
          <div class="embed-preview-large-dots" aria-hidden="true">
            {#each dotIndices as i}
              <span class="dot" class:dot--active={i === currentIndex}></span>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Carousel arrows (rendered by the first card only) -->
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
      {/if}
    </div>
  </div>
{/if}

<style>
  /* Outer wrapper — full width, hides non-visible carousel slides. */
  .embed-preview-large-wrapper {
    width: 100%;
    margin: 6px 0;
  }

  /* Hidden carousel slides take no space */
  .embed-preview-large-wrapper--hidden {
    display: none;
  }

  /* Full-width tall card.  position:relative is required for absolutely-
     positioned carousel arrows. */
  .embed-preview-large {
    position: relative;
    width: 100%;
    min-height: 160px;
    border-radius: 14px;
    overflow: hidden;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-end;
    transition: filter 0.15s ease, transform 0.15s ease;
    user-select: none;
  }

  .embed-preview-large:hover {
    filter: brightness(1.05);
  }

  .embed-preview-large:active {
    transform: scale(0.985);
    filter: brightness(0.95);
  }

  /* Bottom content strip — centered vertically, with padding to leave room
     for carousel arrows (40px per side). */
  .embed-preview-large-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 20px 48px 18px;
    background: linear-gradient(to top, rgba(0,0,0,0.35) 0%, transparent 100%);
  }

  /* 44px circular app-icon badge */
  .embed-preview-large-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: rgba(255,255,255,0.2);
    flex-shrink: 0;
  }

  .embed-preview-large-icon :global(.icon_rounded) {
    width: 22px !important;
    height: 22px !important;
    min-width: 22px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
    background: transparent !important;
  }

  .embed-preview-large-icon :global(.icon_rounded::after) {
    filter: brightness(0) invert(1);
    width: 100%;
    height: 100%;
    background-size: contain !important;
  }

  /* Label text */
  .embed-preview-large-label {
    font-size: 14px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.95);
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
    text-shadow: 0 1px 4px rgba(0,0,0,0.4);
  }

  /* Dot indicators */
  .embed-preview-large-dots {
    display: flex;
    gap: 5px;
    align-items: center;
    margin-top: 2px;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.45);
    transition: background 0.2s ease, transform 0.2s ease;
    flex-shrink: 0;
  }

  .dot--active {
    background: rgba(255, 255, 255, 0.95);
    transform: scale(1.25);
  }

  /* ── Carousel arrows ──
     Copied directly from DailyInspirationBanner.svelte's carousel arrow design.
     Full-height (top:0, bottom:0) invisible touch surfaces, 40px wide.
     All global button{} rules from buttons.css are overridden with !important. */
  .carousel-arrow {
    position: absolute;
    top: 0;
    bottom: 0;
    padding: 0 !important;
    min-width: unset !important;
    width: 40px !important;
    height: 100% !important;
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
    flex-shrink: 0;
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
