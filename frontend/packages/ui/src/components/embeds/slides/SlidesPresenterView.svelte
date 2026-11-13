<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesPresenterView.svelte

  The presenter's own window: the current slide, a preview of the next slide,
  the speaker notes of the current slide, the slide position, an elapsed timer
  with reset and previous/next controls. The audience sees only the other
  window; speaker notes exist only here. The position is owned by the parent.
-->
<script lang="ts">
  import SlideCanvas from './SlideCanvas.svelte';
  import EmbedChevron from '../EmbedChevron.svelte';
  import {
    actionForKey,
    formatElapsed,
    isTypingTarget,
    type PresentAction,
    type PresentPosition
  } from './slidesPresentation';
  import { maxStep, type Deck } from './slidesMarkup';
  import { text } from '@repo/ui';

  interface Props {
    deck: Deck;
    position: PresentPosition;
    onAction: (action: Exclude<PresentAction, 'exit'>) => void;
    onExit: () => void;
    /** Jumps to the first state of a slide (slide list). */
    onGoto: (index: number) => void;
    /** Shown when the second window could not open and presenting continues here. */
    notice?: string;
  }

  let { deck, position, onAction, onExit, onGoto, notice = '' }: Props = $props();

  const TICK_MS = 1000;

  let slides = $derived(deck.slides);
  let current = $derived(slides[Math.min(position.index, slides.length - 1)]);
  /** What the audience sees after the next advance: the next build step, else the next slide. */
  let upcoming = $derived.by(() => {
    if (current && position.step < maxStep(current)) return { slide: current, step: position.step + 1 };
    const following = slides[position.index + 1];
    return following ? { slide: following, step: 0 } : null;
  });
  let canGoPrevious = $derived(position.index > 0 || position.step > 0);
  let canGoNext = $derived(
    position.index < slides.length - 1 || (current ? position.step < maxStep(current) : false)
  );
  let ratio = $derived(deck.width / deck.height);

  let startedAt = $state(Date.now());
  let elapsedSeconds = $state(0);

  $effect(() => {
    const timer = setInterval(() => {
      elapsedSeconds = (Date.now() - startedAt) / 1000;
    }, TICK_MS);
    return () => clearInterval(timer);
  });

  function resetTimer() {
    startedAt = Date.now();
    elapsedSeconds = 0;
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || isTypingTarget(event.target)) return;
    const action = actionForKey(event.key);
    if (!action) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (action === 'exit') onExit();
    else onAction(action);
  }

  $effect(() => {
    window.addEventListener('keydown', onKeydown, true);
    return () => window.removeEventListener('keydown', onKeydown, true);
  });
</script>

<div
  class="presenter"
  data-testid="slides-presenter"
  data-slide-index={position.index}
  data-step={position.step}
  style:--slide-ratio={ratio}
>
  <header class="bar">
    <span class="position" data-testid="presenter-position">{position.index + 1} / {slides.length}</span>
    <span class="timer" data-testid="presenter-timer" role="timer">{formatElapsed(elapsedSeconds)}</span>
    <button type="button" class="presenter-text-button" data-testid="presenter-timer-reset" onclick={resetTimer}>
      {$text('embeds.slides_timer_reset')}
    </button>
    <span class="spacer"></span>
    <button type="button" class="presenter-text-button" data-testid="presenter-exit" onclick={onExit}>
      {$text('embeds.slides_exit_presentation')}
    </button>
  </header>

  {#if notice}
    <p class="notice" data-testid="slides-popup-blocked-notice">{notice}</p>
  {/if}

  <div class="body">
    <section class="main">
      <div class="current" data-testid="presenter-current">
        {#if current}
          {#key current.id}
            <SlideCanvas
              slide={current}
              width={deck.width}
              height={deck.height}
              template={deck.template}
              step={position.step}
              interactive={true}
              animated={true}
            />
          {/key}
        {/if}
      </div>
      <div class="controls">
        <button
          type="button"
          class="nav-button"
          data-testid="presenter-prev"
          aria-label={$text('embeds.slides_prev')}
          disabled={!canGoPrevious}
          onclick={() => onAction('previous')}
        ><EmbedChevron direction="previous" /></button>
        <button
          type="button"
          class="nav-button"
          data-testid="presenter-next"
          aria-label={$text('embeds.slides_next')}
          disabled={!canGoNext}
          onclick={() => onAction('next')}
        ><EmbedChevron direction="next" /></button>
      </div>
      <div class="slide-list" role="list" data-testid="presenter-slide-list" aria-label={$text('embeds.slides_strip_label')}>
        {#each slides as slide, i (slide.id)}
          <button
            type="button"
            class="list-item"
            class:active={i === position.index}
            style:aspect-ratio="{deck.width} / {deck.height}"
            data-testid="presenter-slide-list-item"
            aria-label="{$text('embeds.slides_slide_label')} {i + 1}"
            aria-current={i === position.index ? 'true' : undefined}
            onclick={() => onGoto(i)}
          >
            <SlideCanvas slide={slide} width={deck.width} height={deck.height} template={deck.template} />
          </button>
        {/each}
      </div>
    </section>

    <aside class="side">
      <section class="next" data-testid="presenter-next-slide" aria-label={$text('embeds.slides_next')}>
        <h3>{$text('embeds.slides_next')}</h3>
        {#if upcoming}
          {#key `${upcoming.slide.id}:${upcoming.step}`}
            <SlideCanvas
              slide={upcoming.slide}
              width={deck.width}
              height={deck.height}
              template={deck.template}
              step={upcoming.step}
            />
          {/key}
        {:else}
          <div class="no-next" style:aspect-ratio="{deck.width} / {deck.height}"></div>
        {/if}
      </section>
      <section class="notes" data-testid="presenter-notes" aria-label={$text('embeds.slides_speaker_notes')}>
        <h3>{$text('embeds.slides_speaker_notes')}</h3>
        {#if current?.notes}
          <p class="notes-text">{current.notes}</p>
        {:else}
          <p class="notes-empty">{$text('embeds.slides_no_notes')}</p>
        {/if}
      </section>
    </aside>
  </div>
</div>

<style>
  .presenter {
    position: fixed;
    inset: 0;
    z-index: 10000;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    padding: var(--spacing-8);
    box-sizing: border-box;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    overflow: auto;
  }

  .bar {
    display: flex;
    align-items: center;
    gap: var(--spacing-8);
    flex: none;
  }

  .position,
  .timer {
    font-size: var(--font-size-h3);
    font-variant-numeric: tabular-nums;
  }

  .spacer {
    flex: 1;
  }

  /* Not `.text-button`: auth.css defines a global one with transparent text. */
  .presenter-text-button {
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: var(--spacing-3) var(--spacing-6);
    border: 0;
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    font-size: var(--font-size-small);
    cursor: pointer;
  }

  .presenter-text-button:hover,
  .list-item:hover {
    background: var(--color-grey-0);
    scale: 1;
  }

  .list-item:hover {
    background: none;
  }

  .notice {
    margin: 0;
    padding: var(--spacing-4) var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .body {
    display: grid;
    grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
    gap: var(--spacing-8);
    flex: 1;
    min-height: 0;
  }

  .main {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-6);
    min-width: 0;
  }

  .current {
    width: 100%;
    /* Never taller than the window leaves room for: the width follows the available height. */
    max-width: calc((100dvh - 22 * var(--spacing-8)) * var(--slide-ratio));
    border-radius: var(--radius-3);
    overflow: hidden;
  }

  .controls {
    display: flex;
    gap: var(--spacing-8);
  }

  .nav-button {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
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

  .nav-button:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .side {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    min-width: 0;
    min-height: 0;
  }

  h3 {
    margin: 0 0 var(--spacing-3);
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
  }

  .next {
    /* The next slide is a reminder, notes get the room. */
    width: 55%;
    flex: none;
  }

  .slide-list {
    display: flex;
    gap: var(--spacing-4);
    width: 100%;
    overflow-x: auto;
    padding: var(--spacing-2) 0;
    flex: none;
  }

  .list-item {
    flex: 0 0 auto;
    height: 64px;
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    border: 2px solid transparent;
    border-radius: var(--radius-2);
    background: none;
    filter: none;
    overflow: hidden;
    cursor: pointer;
  }

  .list-item.active {
    border-color: var(--color-primary-start);
    /* Clearly stronger than the focus ring a previously clicked thumbnail keeps. */
    box-shadow: 0 0 0 2px var(--color-primary-start);
  }

  .list-item :global(.slide-viewport) {
    height: 100%;
    pointer-events: none;
  }

  .no-next {
    width: 100%;
    border-radius: var(--radius-2);
    background: var(--color-grey-20);
  }

  .notes {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
  }

  .notes-text,
  .notes-empty {
    margin: 0;
    font-size: var(--font-size-h3);
    line-height: 1.4;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .notes-empty {
    color: var(--color-font-tertiary);
  }

  @media (max-width: 800px) {
    .body {
      grid-template-columns: minmax(0, 1fr);
    }

    .next {
      width: 100%;
    }
  }
</style>
