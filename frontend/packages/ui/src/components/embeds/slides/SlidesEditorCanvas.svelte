<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditorCanvas.svelte

  Editable slide of the slides editor. Draws the core's slide with the read-only
  SlideCanvas and lays an interaction layer over it in canvas units (1920 wide,
  scaled like the slide): one hit box per element, the selection frame with eight
  resize handles and, while typing, a contenteditable box over the text element.
  Pointer events cover mouse, pen and touch; the drag rectangle is view state and
  only pointer-up sends one `set_geometry` through `onGeometry`.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import { text } from '@repo/ui';
  import SlideCanvas from './SlideCanvas.svelte';
  import { getTemplate, placeElements, templateStyleVars } from './slidesTemplates';
  import { fillEditable, editableToMarkup } from './slidesEditorText';
  import {
    dragBox,
    effectiveTextStyle,
    RESIZE_HANDLES,
    sameBox,
    selectable,
    toRenderSlide,
    type CanvasBox,
    type ResizeHandle
  } from './slidesEditorView';
  import type { DeckSlideModel } from '../../../services/rustCore/deckDocument/deckDocumentTypes';
  import { parseInlineMarkup, type InlineNode } from './slidesMarkup';

  interface Props {
    slide: DeckSlideModel;
    width: number;
    height: number;
    template: string;
    selectedId: string | null;
    typingId: string | null;
    onSelect: (elementId: string | null) => void;
    /** Resolves once the core answered, so the drag rectangle can be dropped. */
    onGeometry: (elementId: string, box: CanvasBox) => Promise<void>;
    onStartTyping: (elementId: string) => void;
    onCommitText: (elementId: string, markup: string) => void;
  }

  let { slide, width, height, template: templateId, selectedId, typingId, onSelect, onGeometry, onStartTyping, onCommitText }: Props =
    $props();

  /** Pointer travel (screen px) below which a press is a click, not a drag. */
  const CLICK_SLOP = 3;

  let stageWidth = $state(0);
  let scale = $derived(stageWidth > 0 ? stageWidth / width : 0);
  let template = $derived(getTemplate(templateId));
  let drag = $state<{ elementId: string; box: CanvasBox } | null>(null);
  let renderSlide = $derived(toRenderSlide(slide, { drag, typingId }));
  let placed = $derived(placeElements(renderSlide, template, height));
  let hits = $derived(selectable(placed));
  let selected = $derived(hits.find((entry) => entry.element.id === selectedId) ?? null);
  let typingEntry = $derived(typingId ? placed.find((entry) => entry.element.id === typingId) ?? null : null);
  /** Unscaled size of a handle: always about 14 screen px. */
  let handleSize = $derived(scale > 0 ? 14 / scale : 14);
  let frameWidth = $derived(scale > 0 ? 2 / scale : 2);

  let layerEl = $state<HTMLElement | null>(null);

  interface Gesture {
    pointerId: number;
    elementId: string;
    handle: ResizeHandle | 'move';
    startX: number;
    startY: number;
    unitsPerPixel: number;
    start: CanvasBox;
    moved: boolean;
    wasSelected: boolean;
  }
  let gesture: Gesture | null = null;

  function boxStyle(box: CanvasBox): string {
    return `left:${box.x}px;top:${box.y}px;width:${box.w}px;height:${box.h}px`;
  }

  function beginGesture(event: PointerEvent, elementId: string, handle: ResizeHandle | 'move', start: CanvasBox) {
    if (event.button !== 0 || !layerEl) return;
    event.stopPropagation();
    event.preventDefault();
    const rect = layerEl.getBoundingClientRect();
    gesture = {
      pointerId: event.pointerId,
      elementId,
      handle,
      startX: event.clientX,
      startY: event.clientY,
      // Measured, not derived from the transform: correct at any zoom or page scale.
      unitsPerPixel: rect.width > 0 ? width / rect.width : 1,
      start,
      moved: false,
      wasSelected: selectedId === elementId
    };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    if (selectedId !== elementId) onSelect(elementId);
  }

  function moveGesture(event: PointerEvent) {
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    const dxPx = event.clientX - gesture.startX;
    const dyPx = event.clientY - gesture.startY;
    if (!gesture.moved && Math.hypot(dxPx, dyPx) < CLICK_SLOP) return;
    gesture.moved = true;
    const box = dragBox(gesture.start, gesture.handle, dxPx * gesture.unitsPerPixel, dyPx * gesture.unitsPerPixel, { width, height });
    drag = { elementId: gesture.elementId, box };
  }

  function endGesture(event: PointerEvent) {
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    const finished = gesture;
    gesture = null;
    const current = drag;
    if (!finished.moved || !current || sameBox(current.box, finished.start)) {
      drag = null;
      // A second tap on a selected text box starts typing (touch has no reliable dblclick).
      if (!finished.moved && finished.wasSelected && finished.handle === 'move') {
        const entry = hits.find((candidate) => candidate.element.id === finished.elementId);
        if (entry?.element.type === 'text') onStartTyping(finished.elementId);
      }
      return;
    }
    void onGeometry(current.elementId, current.box).finally(() => {
      if (drag === current) drag = null;
    });
  }

  function cancelGesture(event: PointerEvent) {
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    gesture = null;
    drag = null;
  }

  function onBackgroundPointerDown(event: PointerEvent) {
    if (event.target === event.currentTarget || event.target === layerEl) onSelect(null);
  }

  function onHitKeydown(event: KeyboardEvent, elementId: string, isText: boolean) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (selectedId === elementId && isText) onStartTyping(elementId);
      else onSelect(elementId);
    }
  }

  function textStyleCss(): string {
    if (!typingEntry) return '';
    const style = effectiveTextStyle(typingEntry, template);
    if (!style) return '';
    const parts = [
      `font-size:${style.size}px`,
      `font-weight:${style.weight}`,
      `text-align:${style.align}`,
      `font-family:${style.font}`
    ];
    if (style.color) parts.push(`color:${style.color}`);
    if (style.italic) parts.push('font-style:italic');
    return parts.join(';');
  }

  /** Content of the box when typing starts; later core views must not reset the caret. */
  function typingContent(): InlineNode[] {
    const element = slide.elements.find((candidate) => candidate.id === typingId);
    if (!element || element.kind !== 'text' || element.content.type !== 'rich_text') return [];
    return parseInlineMarkup(element.content.value);
  }

  function editable(node: HTMLElement, elementId: string) {
    fillEditable(node, untrack(typingContent));
    node.focus();
    const range = document.createRange();
    range.selectNodeContents(node);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    let committed = false;
    const commit = () => {
      if (committed) return;
      committed = true;
      onCommitText(elementId, editableToMarkup(node));
    };
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        node.blur();
      }
    };
    node.addEventListener('blur', commit);
    node.addEventListener('keydown', onKeydown);
    return {
      destroy() {
        node.removeEventListener('blur', commit);
        node.removeEventListener('keydown', onKeydown);
        commit();
      }
    };
  }
</script>

<div class="slides-editor-stage" bind:clientWidth={stageWidth} data-testid="slides-editor-canvas" data-slide-id={slide.id}>
  {#key slide.id}
    <SlideCanvas slide={renderSlide} {width} {height} template={templateId} />
  {/key}
  <!-- Pointer surface; every element below is reachable by keyboard. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="slides-editor-overlay"
    onpointerdown={onBackgroundPointerDown}
    onpointermove={moveGesture}
    onpointerup={endGesture}
    onpointercancel={cancelGesture}
  >
    {#if scale > 0}
      <!-- Empty canvas area: a press deselects. -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="slides-editor-layer"
        bind:this={layerEl}
        style="{templateStyleVars(template)};width:{width}px;height:{height}px;transform:scale({scale})"
      >
        {#each hits as entry, position (entry.element.id)}
          {@const element = entry.element}
          <div
            class="slides-editor-hit"
            class:is-selected={element.id === selectedId}
            style={boxStyle(entry.box)}
            role="button"
            tabindex="0"
            aria-label="{$text('embeds.slides_editor_element')} {position + 1}"
            aria-pressed={element.id === selectedId}
            data-testid="slides-editor-element"
            data-element-id={element.id}
            data-kind={element.type}
            data-x={entry.box.x}
            data-y={entry.box.y}
            data-w={entry.box.w}
            data-h={entry.box.h}
            onpointerdown={(event) => beginGesture(event, element.id, 'move', entry.box)}
            ondblclick={() => {
              if (element.type === 'text') onStartTyping(element.id);
            }}
            onkeydown={(event) => onHitKeydown(event, element.id, element.type === 'text')}
          ></div>
        {/each}

        {#if selected && selected.element.id !== typingId}
          <div
            class="slides-editor-frame"
            style="{boxStyle(selected.box)};--frame-width:{frameWidth}px"
            data-testid="slides-editor-selection"
            data-element-id={selected.element.id}
          >
            {#each RESIZE_HANDLES as handle (handle)}
              <!-- Pointer-only handle; keyboard users resize with Alt+arrow keys. -->
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div
                class="slides-editor-handle slides-editor-handle-{handle}"
                style="--handle-size:{handleSize}px"
                data-testid="slides-editor-handle"
                data-handle={handle}
                onpointerdown={(event) => beginGesture(event, selected.element.id, handle, selected.box)}
              ></div>
            {/each}
          </div>
        {/if}

        {#if typingEntry && typingId}
          <!-- Plain commit on blur/Escape; the Yjs rich-text mirror arrives with live collaboration. -->
          <div
            class="slides-editor-typing"
            style="{boxStyle(typingEntry.box)};{textStyleCss()}"
            contenteditable="true"
            role="textbox"
            tabindex="0"
            aria-multiline="true"
            aria-label={$text('embeds.slides_editor_text_box')}
            data-testid="slides-editor-text-input"
            data-element-id={typingId}
            onpointerdown={(event) => event.stopPropagation()}
            use:editable={typingId}
          ></div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  /* Not clipped: the selection handles sit outside the frame, also at the slide edges.
     The slide itself (SlideCanvas viewport) clips its content and carries the radius. */
  .slides-editor-stage {
    position: relative;
    width: 100%;
    overflow: visible;
  }

  .slides-editor-stage :global(.slide-viewport) {
    border-radius: var(--radius-3);
  }

  .slides-editor-overlay {
    position: absolute;
    inset: 0;
    z-index: 2;
    touch-action: none;
    user-select: none;
  }

  .slides-editor-layer {
    position: absolute;
    top: 0;
    left: 0;
    transform-origin: top left;
  }

  .slides-editor-hit {
    position: absolute;
    box-sizing: border-box;
    cursor: move;
    touch-action: none;
  }

  .slides-editor-hit:hover:not(.is-selected) {
    box-shadow: inset 0 0 0 3px color-mix(in srgb, var(--color-primary-start) 45%, transparent);
  }

  .slides-editor-hit:focus-visible {
    outline: 6px solid var(--color-button-primary);
    outline-offset: 4px;
  }

  .slides-editor-frame {
    position: absolute;
    box-sizing: border-box;
    border: var(--frame-width) solid var(--color-primary-start);
    pointer-events: none;
    touch-action: none;
  }

  .slides-editor-handle {
    position: absolute;
    box-sizing: border-box;
    width: var(--handle-size);
    height: var(--handle-size);
    margin: calc(var(--handle-size) / -2) 0 0 calc(var(--handle-size) / -2);
    padding: 0;
    border: calc(var(--handle-size) / 7) solid var(--color-primary-start);
    border-radius: 50%;
    background: var(--color-grey-0);
    pointer-events: auto;
    touch-action: none;
  }

  /* Larger invisible touch area around each handle. */
  .slides-editor-handle::before {
    content: '';
    position: absolute;
    inset: calc(var(--handle-size) / -1.2);
  }

  /* Handles sit just outside the frame so they never cover the content of a small element. */
  .slides-editor-handle-nw { left: calc(var(--handle-size) / -2); top: calc(var(--handle-size) / -2); cursor: nwse-resize; }
  .slides-editor-handle-n { left: 50%; top: calc(var(--handle-size) / -2); cursor: ns-resize; }
  .slides-editor-handle-ne { left: calc(100% + var(--handle-size) / 2); top: calc(var(--handle-size) / -2); cursor: nesw-resize; }
  .slides-editor-handle-e { left: calc(100% + var(--handle-size) / 2); top: 50%; cursor: ew-resize; }
  .slides-editor-handle-se { left: calc(100% + var(--handle-size) / 2); top: calc(100% + var(--handle-size) / 2); cursor: nwse-resize; }
  .slides-editor-handle-s { left: 50%; top: calc(100% + var(--handle-size) / 2); cursor: ns-resize; }
  .slides-editor-handle-sw { left: calc(var(--handle-size) / -2); top: calc(100% + var(--handle-size) / 2); cursor: nesw-resize; }
  .slides-editor-handle-w { left: calc(var(--handle-size) / -2); top: 50%; cursor: ew-resize; }

  .slides-editor-typing {
    position: absolute;
    box-sizing: border-box;
    line-height: 1.25;
    overflow-wrap: anywhere;
    overflow: auto;
    outline: 4px solid var(--color-primary-start);
    background: color-mix(in srgb, var(--slide-color-background) 92%, transparent);
    color: var(--slide-color-foreground);
    cursor: text;
    user-select: text;
    white-space: pre-wrap;
  }

  .slides-editor-typing :global(ul),
  .slides-editor-typing :global(ol) {
    margin: 0;
    padding-inline-start: 1.2em;
  }
</style>
