<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditorStrip.svelte

  Slide strip of the slides editor: thumbnails of the core's slides (click to
  open one) and the actions for the open slide: add, duplicate, move left/right
  and delete. Every action is a button, so reordering works by keyboard and
  touch; SlidesEditor sends the matching core operation.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import SlideCanvas from './SlideCanvas.svelte';
  import { toRenderSlide } from './slidesEditorView';
  import type { DeckSlideModel } from '../../../services/rustCore/deckDocument/deckDocumentTypes';

  interface Props {
    slides: DeckSlideModel[];
    width: number;
    height: number;
    template: string;
    currentId: string;
    onOpen: (slideId: string) => void;
    onAdd: () => void;
    onDuplicate: () => void;
    onDelete: () => void;
    onMove: (delta: -1 | 1) => void;
  }

  let { slides, width, height, template, currentId, onOpen, onAdd, onDuplicate, onDelete, onMove }: Props = $props();

  let position = $derived(slides.findIndex((slide) => slide.id === currentId));

  function slideLabel(index: number): string {
    return `${$text('embeds.slides_slide_label')} ${index + 1}`;
  }
</script>

<div class="slides-editor-strip-wrap">
  <div class="slides-editor-strip-actions" role="group" aria-label={$text('embeds.slides_editor_slide_actions')}>
    <button type="button" class="slides-editor-strip-tool" data-testid="slides-editor-add-slide" onclick={onAdd}>
      {$text('embeds.slides_editor_add_slide')}
    </button>
    <button type="button" class="slides-editor-strip-tool" data-testid="slides-editor-duplicate-slide" onclick={onDuplicate}>
      {$text('embeds.slides_editor_duplicate_slide')}
    </button>
    <button
      type="button"
      class="slides-editor-strip-tool"
      data-testid="slides-editor-move-slide-left"
      aria-label={$text('embeds.slides_editor_move_left')}
      disabled={position <= 0}
      onclick={() => onMove(-1)}
    >←</button>
    <button
      type="button"
      class="slides-editor-strip-tool"
      data-testid="slides-editor-move-slide-right"
      aria-label={$text('embeds.slides_editor_move_right')}
      disabled={position < 0 || position >= slides.length - 1}
      onclick={() => onMove(1)}
    >→</button>
    <button
      type="button"
      class="slides-editor-strip-tool"
      data-testid="slides-editor-delete-slide"
      disabled={slides.length <= 1}
      onclick={onDelete}
    >{$text('embeds.slides_editor_delete_slide')}</button>
  </div>

  <div class="slides-editor-strip" role="list" aria-label={$text('embeds.slides_strip_label')}>
    {#each slides as slide, index (slide.id)}
      <div role="listitem" class="slides-editor-strip-cell">
        <button
          type="button"
          class="slides-editor-thumb"
          class:active={slide.id === currentId}
          style:aspect-ratio="{width} / {height}"
          data-testid="slides-editor-strip-item"
          data-slide-id={slide.id}
          aria-label={slideLabel(index)}
          aria-current={slide.id === currentId ? 'true' : undefined}
          onclick={() => onOpen(slide.id)}
        >
          <SlideCanvas slide={toRenderSlide(slide)} {width} {height} {template} />
        </button>
      </div>
    {/each}
  </div>
</div>

<style>
  .slides-editor-strip-wrap {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    width: 100%;
    min-width: 0;
  }

  .slides-editor-strip-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
  }

  /* Reset of the global button sizing (buttons.css). */
  .slides-editor-strip-tool {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 36px;
    min-height: 36px;
    height: auto;
    margin: 0;
    padding: var(--spacing-2) var(--spacing-6);
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    font-size: var(--font-size-small);
    line-height: 1.2;
    cursor: pointer;
    transform: none;
  }

  .slides-editor-strip-tool:hover:not(:disabled) {
    background: var(--color-grey-10);
    transform: none;
  }

  .slides-editor-strip-tool:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .slides-editor-strip-tool:focus-visible,
  .slides-editor-thumb:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  .slides-editor-strip {
    display: flex;
    gap: var(--spacing-4);
    width: 100%;
    overflow-x: auto;
    padding: var(--spacing-2) var(--spacing-2) var(--spacing-4);
    box-sizing: border-box;
  }

  .slides-editor-strip-cell {
    flex: 0 0 auto;
  }

  .slides-editor-thumb {
    display: block;
    height: 64px;
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
    transform: none;
  }

  .slides-editor-thumb.active {
    border-color: var(--color-primary-start);
    box-shadow: 0 0 0 2px var(--color-primary-start);
  }

  .slides-editor-thumb :global(.slide-viewport) {
    height: 100%;
    pointer-events: none;
  }
</style>
