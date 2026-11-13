<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditorStrip.svelte

  Slide strip of the slides editor: thumbnails of the core's slides (click to
  open one), a round "add slide" button at the end of the strip, and one round
  "slide actions" button that opens a small row of round icon buttons for the
  open slide: duplicate, move earlier/later and delete (EmbedIconButton, tooltips
  name each action; Escape or a press outside closes the row). Every action is a
  button, so reordering works by keyboard and touch; SlidesEditor sends the
  matching core operation. View state here: whether the action row is open.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { text } from '@repo/ui';
  import SlideCanvas from './SlideCanvas.svelte';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';
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

  const actionsId = $props.id();
  let position = $derived(slides.findIndex((slide) => slide.id === currentId));
  let actionsOpen = $state(false);
  let anchor = $state<HTMLElement | null>(null);
  let trigger = $state<HTMLButtonElement | null>(null);

  function slideLabel(index: number): string {
    return `${$text('embeds.slides_slide_label')} ${index + 1}`;
  }

  async function toggleActions() {
    actionsOpen = !actionsOpen;
    if (!actionsOpen) return;
    await tick();
    anchor?.querySelector<HTMLElement>('.slides-editor-slide-actions button:not(:disabled)')?.focus();
  }

  function onAnchorKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && actionsOpen) {
      event.preventDefault();
      event.stopPropagation();
      actionsOpen = false;
      trigger?.focus();
    }
  }

  function onWindowPointerDown(event: PointerEvent) {
    if (actionsOpen && event.target instanceof Node && !anchor?.contains(event.target)) actionsOpen = false;
  }
</script>

<svelte:window onpointerdown={onWindowPointerDown} />

<div class="slides-editor-strip-wrap">
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
    <div role="listitem" class="slides-editor-strip-cell slides-editor-strip-add">
      <EmbedIconButton icon="plus" label={$text('embeds.slides_editor_add_slide')} testId="slides-editor-add-slide" onclick={onAdd} />
    </div>
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="slides-editor-slide-actions-anchor" bind:this={anchor} onkeydown={onAnchorKeydown}>
    <EmbedIconButton
      icon="more"
      label={$text('embeds.slides_editor_slide_actions')}
      testId="slides-editor-slide-actions"
      expanded={actionsOpen}
      controls={actionsId}
      bind:element={trigger}
      onclick={toggleActions}
    />
    {#if actionsOpen}
      <div
        id={actionsId}
        class="slides-editor-slide-actions"
        role="group"
        aria-label={$text('embeds.slides_editor_slide_actions')}
        data-testid="slides-editor-slide-actions-menu"
      >
        <EmbedIconButton icon="copy" label={$text('embeds.slides_editor_duplicate_slide')} testId="slides-editor-duplicate-slide" onclick={onDuplicate} />
        <EmbedIconButton
          icon="back"
          label={$text('embeds.slides_editor_move_left')}
          testId="slides-editor-move-slide-left"
          disabled={position <= 0}
          onclick={() => onMove(-1)}
        />
        <EmbedIconButton
          icon="back"
          flip
          label={$text('embeds.slides_editor_move_right')}
          testId="slides-editor-move-slide-right"
          disabled={position < 0 || position >= slides.length - 1}
          onclick={() => onMove(1)}
        />
        <EmbedIconButton
          icon="delete"
          label={$text('embeds.slides_editor_delete_slide')}
          testId="slides-editor-delete-slide"
          disabled={slides.length <= 1}
          onclick={onDelete}
        />
      </div>
    {/if}
  </div>
</div>

<style>
  .slides-editor-strip-wrap {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    width: 100%;
    min-width: 0;
  }

  .slides-editor-strip {
    flex: 1 1 auto;
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    min-width: 0;
    overflow-x: auto;
    /* Room for the active ring, hover scale and shadows inside the scroller. */
    padding: var(--spacing-4);
    box-sizing: border-box;
  }

  .slides-editor-strip-cell {
    flex: 0 0 auto;
  }

  .slides-editor-strip-add {
    display: flex;
    align-items: center;
    padding-inline: var(--spacing-2);
  }

  /* Reset of the global button sizing (buttons.css). */
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

  .slides-editor-thumb:focus-visible {
    outline: 2px solid var(--color-primary-start);
    outline-offset: 2px;
  }

  .slides-editor-thumb.active {
    border-color: var(--color-primary-start);
    box-shadow: 0 0 0 2px var(--color-primary-start);
  }

  .slides-editor-thumb :global(.slide-viewport) {
    height: 100%;
    pointer-events: none;
  }

  .slides-editor-slide-actions-anchor {
    position: relative;
    flex: 0 0 auto;
  }

  /* Opens upwards, ending at the trigger, like the fullscreen More menu opens from its button. */
  .slides-editor-slide-actions {
    position: absolute;
    right: 0;
    bottom: calc(100% + var(--spacing-6));
    z-index: 5;
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
  }
</style>
