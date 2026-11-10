<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedFullscreen.svelte

  Read-only fullscreen viewer of a slide deck embed: the current slide large, a
  strip of slide thumbnails, previous/next buttons and arrow keys (build steps
  advance before the slide changes) and the shared version timeline. While the
  deck still streams only completed slides are shown. No editor, presenter view
  or export yet (later phases of the slides-core plan).
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import EmbedChevron from '../EmbedChevron.svelte';
  import SlideCanvas from './SlideCanvas.svelte';
  import { inlineToPlainText, maxStep, parseSlidesMarkup } from './slidesMarkup';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    chatId?: string;
    projectId?: string;
    teamId?: string | null;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    chatId,
    projectId,
    teamId
  }: Props = $props();

  let dc = $derived(data.decodedContent);
  let latestMarkup = $derived(typeof dc.slides_markup === 'string' ? dc.slides_markup : '');
  /** Markup of a version picked in the timeline; null shows the latest. */
  let selectedMarkup = $state<string | null>(null);
  let markup = $derived(selectedMarkup ?? latestMarkup);
  let streaming = $derived(data.embedData?.status === 'processing');
  let versionNumber = $derived(
    typeof dc.version_number === 'number' ? dc.version_number : (data.embedData?.version_number ?? 1)
  );

  let parsed = $derived(parseSlidesMarkup(markup, { partial: streaming }));
  let deck = $derived(parsed.ok ? parsed.deck : null);
  let slides = $derived(deck?.slides ?? []);
  let title = $derived(
    (typeof dc.title === 'string' && dc.title) || deck?.title || $text('embeds.slides_deck_default_title')
  );
  let statusText = $derived(
    slides.length > 0
      ? `${slides.length} ${slides.length === 1 ? $text('embeds.slides_count_singular') : $text('embeds.slides_count_plural')}`
      : ''
  );

  let index = $state(0);
  let step = $state(0);
  let current = $derived(slides[Math.min(index, Math.max(slides.length - 1, 0))]);
  let canGoPrevious = $derived(index > 0 || step > 0);
  let canGoNext = $derived(index < slides.length - 1 || (current ? step < maxStep(current) : false));

  $effect(() => {
    if (index > slides.length - 1) index = Math.max(slides.length - 1, 0);
  });

  function next() {
    if (!current) return;
    if (step < maxStep(current)) step += 1;
    else if (index < slides.length - 1) {
      index += 1;
      step = 0;
    }
  }

  function previous() {
    if (step > 0) step -= 1;
    else if (index > 0) {
      index -= 1;
      step = maxStep(slides[index]);
    }
  }

  function select(target: number) {
    index = target;
    step = 0;
  }

  function onKeydown(event: KeyboardEvent) {
    const target = event.target as HTMLElement | null;
    if (target && (target.isContentEditable || /^(input|textarea|select)$/i.test(target.tagName))) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown' || event.key === 'PageDown') {
      event.preventDefault();
      next();
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp' || event.key === 'PageUp') {
      event.preventDefault();
      previous();
    }
  }

  /**
   * The slide must leave room for the controls and the thumbnail strip inside
   * the window, whatever the header height is, so its width is derived from the
   * measured space below the top of the stage.
   */
  let stageEl = $state<HTMLElement | null>(null);
  let belowEl = $state<HTMLElement | null>(null);
  let stageMaxWidth = $state('100%');
  const MIN_STAGE_HEIGHT = 120;
  const STAGE_BOTTOM_MARGIN = 32;

  function fitStage() {
    if (!stageEl || !belowEl || !deck) return;
    // Layout offsets, not getBoundingClientRect: the fullscreen slides in with a
    // transform and can be scrolled, and neither may change the slide size.
    let top = 0;
    for (let node: HTMLElement | null = stageEl; node; node = node.offsetParent as HTMLElement | null) {
      top += node.offsetTop;
    }
    const available = window.innerHeight - top - belowEl.offsetHeight - STAGE_BOTTOM_MARGIN;
    const height = Math.max(available, MIN_STAGE_HEIGHT);
    stageMaxWidth = `min(100%, ${Math.floor(height * (deck.width / deck.height))}px)`;
  }

  $effect(() => {
    if (!stageEl || !belowEl || !deck) return;
    fitStage();
    const observer = new ResizeObserver(fitStage);
    observer.observe(belowEl);
    if (stageEl.parentElement) observer.observe(stageEl.parentElement);
    window.addEventListener('resize', fitStage);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', fitStage);
    };
  });

  function slideLabel(position: number): string {
    return `${$text('embeds.slides_slide_label')} ${position + 1}`;
  }

  async function handleCopy() {
    const lines = [title];
    slides.forEach((slide, position) => {
      lines.push(`\n${slideLabel(position)}`);
      for (const element of slide.elements) {
        if (element.type === 'text') lines.push(inlineToPlainText(element.content));
      }
      if (slide.notes) lines.push(slide.notes);
    });
    await navigator.clipboard.writeText(lines.join('\n'));
  }
</script>

<svelte:window onkeydown={onKeydown} />

<UnifiedEmbedFullscreen
  appId="slides"
  skillId="deck"
  {onClose}
  onCopy={handleCopy}
  currentEmbedId={embedId}
  skillIconName="slides"
  embedHeaderTitle={title}
  embedHeaderSubtitle={statusText}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="deck-viewer" data-testid="slides-deck-fullscreen" data-slide-index={index}>
      {#if deck && current}
        <div class="stage" bind:this={stageEl} style:max-width={stageMaxWidth}>
          {#key current.id}
            <SlideCanvas
              slide={current}
              width={deck.width}
              height={deck.height}
              template={deck.template}
              {step}
              interactive={true}
              animated={true}
            />
          {/key}
        </div>

        <div class="below-stage" bind:this={belowEl}>
        <div class="controls">
          <button
            type="button"
            class="nav-button"
            data-testid="slide-prev"
            aria-label={$text('embeds.slides_prev')}
            disabled={!canGoPrevious}
            onclick={previous}
          ><EmbedChevron direction="previous" /></button>
          <span class="position" data-testid="slide-position">{index + 1} / {slides.length}</span>
          <button
            type="button"
            class="nav-button"
            data-testid="slide-next"
            aria-label={$text('embeds.slides_next')}
            disabled={!canGoNext}
            onclick={next}
          ><EmbedChevron direction="next" /></button>
        </div>

        <div class="strip" role="list" aria-label={$text('embeds.slides_strip_label')}>
          {#each slides as slide, position (slide.id)}
            <button
              type="button"
              class="strip-item"
              style:aspect-ratio="{deck.width} / {deck.height}"
              class:active={position === index}
              data-testid="slide-strip-item"
              aria-label={slideLabel(position)}
              aria-current={position === index ? 'true' : undefined}
              onclick={() => select(position)}
            >
              <SlideCanvas {slide} width={deck.width} height={deck.height} template={deck.template} />
            </button>
          {/each}
        </div>
        </div>
      {:else}
        <div class="empty-state"><p>{$text('embeds.slides_no_content')}</p></div>
      {/if}

      {#if embedId && versionNumber > 1}
        <EmbedVersionTimeline
          {embedId}
          {chatId}
          {projectId}
          {teamId}
          currentVersion={versionNumber}
          currentContent={latestMarkup}
          buildRestoredContent={(restored, newVersion) => ({ ...dc, slides_markup: restored, version_number: newVersion })}
          onVersionSelect={(_version, selected) => {
            selectedMarkup = selected;
          }}
        />
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .deck-viewer {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-8);
    padding: var(--spacing-8);
    box-sizing: border-box;
    width: 100%;
  }

  .stage {
    width: 100%;
    border-radius: var(--radius-3);
    overflow: hidden;
  }

  .below-stage {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-8);
    width: 100%;
    flex-shrink: 0;
  }

  .controls {
    display: flex;
    align-items: center;
    gap: var(--spacing-8);
    color: var(--color-font-secondary);
  }

  .nav-button {
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    cursor: pointer;
  }

  .nav-button:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  .nav-button:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .strip {
    display: flex;
    gap: var(--spacing-4);
    width: 100%;
    overflow-x: auto;
    padding-bottom: var(--spacing-4);
    flex-shrink: 0;
  }

  .strip-item {
    display: block;
    flex: 0 0 auto;
    height: 72px;
    min-width: 0;
    min-height: 0;
    margin: 0;
    box-sizing: border-box;
    padding: 0;
    border: 2px solid transparent;
    border-radius: var(--radius-2);
    background: none;
    overflow: hidden;
    cursor: pointer;
    pointer-events: auto;
  }

  .strip-item.active {
    border-color: var(--color-primary-start);
  }

  .strip-item :global(.slide-viewport) {
    height: 100%;
    pointer-events: none;
  }

  .empty-state {
    color: var(--color-font-secondary);
    padding: var(--spacing-16);
  }
</style>
