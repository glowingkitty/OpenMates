<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesPresentRemote.svelte

  Phone remote control for a deck presented on another of the owner's devices:
  position, Previous/Next, a slide list to jump, and the CURRENT slide's speaker
  notes read from this device's own copy of the deck (notes are never relayed).
  Shows a not-presenting state when no presenter state is live. Pure view: the
  parent applies moves and publishes them (slidesPresentRemote.ts).
  Spec: slides.present.remote-control.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { inlineToPlainText, parseSlidesMarkup, type Slide } from './slidesMarkup';
  import type { PresentAction, PresentPosition } from './slidesPresentation';

  interface Props {
    markup: string;
    position: PresentPosition;
    presenting: boolean;
    onAction: (action: Extract<PresentAction, 'next' | 'previous'>) => void;
    onGoto: (index: number) => void;
    onClose: () => void;
  }

  let { markup, position, presenting, onAction, onGoto, onClose }: Props = $props();

  let parsed = $derived(parseSlidesMarkup(markup));
  let slides = $derived(parsed.ok ? parsed.deck.slides : []);
  let index = $derived(Math.min(Math.max(position.index, 0), Math.max(slides.length - 1, 0)));
  let notes = $derived(slides[index]?.notes ?? '');
  let notesVisible = $state(false);

  function titleOf(slide: Slide, position: number): string {
    for (const element of slide.elements) {
      if (element.type === 'text' && element.role === 'title') {
        const title = inlineToPlainText(element.content).trim();
        if (title) return title;
      }
    }
    return `${$text('embeds.slides_slide_label')} ${position + 1}`;
  }
</script>

<div class="remote" data-testid="slides-remote-panel" role="region" aria-label={$text('embeds.slides_remote_open')}>
  <div class="header">
    <span class="position" data-testid="slides-remote-position">{index + 1} / {slides.length}</span>
    <button type="button" class="close" data-testid="slides-remote-close" onclick={onClose}>
      {$text('embeds.slides_remote_close')}
    </button>
  </div>

  {#if !presenting}
    <p class="not-presenting" role="status" data-testid="slides-remote-not-presenting">
      {$text('embeds.slides_remote_not_presenting')}
    </p>
  {/if}

  <div class="nav">
    <button
      type="button"
      class="big"
      data-testid="slides-remote-prev"
      aria-label={$text('embeds.slides_prev')}
      disabled={!presenting}
      onclick={() => onAction('previous')}
    >{$text('embeds.slides_prev')}</button>
    <button
      type="button"
      class="big primary"
      data-testid="slides-remote-next"
      aria-label={$text('embeds.slides_next')}
      disabled={!presenting}
      onclick={() => onAction('next')}
    >{$text('embeds.slides_next')}</button>
  </div>

  <button
    type="button"
    class="notes-toggle"
    data-testid="slides-remote-notes-toggle"
    aria-expanded={notesVisible}
    onclick={() => (notesVisible = !notesVisible)}
  >{notesVisible ? $text('embeds.slides_remote_hide_notes') : $text('embeds.slides_remote_show_notes')}</button>
  {#if notesVisible}
    <p class="notes" data-testid="slides-remote-notes">{notes}</p>
  {/if}

  <h3 class="list-title">{$text('embeds.slides_remote_slides')}</h3>
  <ol class="list">
    {#each slides as slide, position (slide.id)}
      <li>
        <button
          type="button"
          class="item"
          class:active={position === index}
          data-testid="slides-remote-slide-{position + 1}"
          aria-current={position === index ? 'true' : undefined}
          disabled={!presenting}
          onclick={() => onGoto(position)}
        >
          <span class="number">{position + 1}</span>
          <span class="title">{titleOf(slide, position)}</span>
        </button>
      </li>
    {/each}
  </ol>
</div>

<style>
  .remote {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    padding: var(--spacing-8);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    min-height: 100%;
    box-sizing: border-box;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .position {
    font-size: var(--font-size-h3);
    font-weight: 600;
  }

  .not-presenting {
    margin: 0;
    padding: var(--spacing-5) var(--spacing-8);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    text-align: center;
  }

  .nav {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--spacing-6);
  }

  button {
    min-width: 0;
    min-height: 0;
    margin: 0;
    border: 0;
    cursor: pointer;
    font-size: var(--font-size-p);
  }

  button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .big {
    min-height: 72px;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    font-size: var(--font-size-h4);
  }

  .big.primary {
    background: var(--color-button-primary);
    color: var(--color-grey-0);
    box-shadow: none;
  }

  .close,
  .notes-toggle {
    min-height: 44px;
    padding: var(--spacing-3) var(--spacing-8);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    font-size: var(--font-size-small);
  }

  .notes {
    margin: 0;
    padding: var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    white-space: pre-wrap;
  }

  .list-title {
    margin: 0;
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .list li {
    margin: 0;
    padding: 0;
  }

  .item {
    box-sizing: border-box;
    max-width: none;
    justify-content: flex-start;
    display: flex;
    align-items: center;
    gap: var(--spacing-6);
    width: 100%;
    min-height: 48px;
    padding: var(--spacing-3) var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    text-align: start;
  }

  .item.active {
    box-shadow: 0 0 0 2px var(--color-primary-start);
  }

  .number {
    font-weight: 600;
    min-width: 2ch;
  }

  .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
