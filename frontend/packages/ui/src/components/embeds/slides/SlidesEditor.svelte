<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditor.svelte

  Manual slides editor (web, single user). The deck lives in the Rust core in the
  shared Worker: the editor opens the markup as a core replica, draws the DeckView
  the core returns and sends one typed operation per change (deckDocumentClient).
  Validation, clamping, ids, undo/redo and markup output are the core's
  (live-collab.core.one-shared-model, slides.editor.direct-manipulation). This file
  keeps view state only: open slide, selection, the text box being typed in and the
  notes draft. Done hands the core's markup to `onSave` when the deck changed;
  persisting it as a new embed version is the caller's job.
-->
<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { text } from '@repo/ui';
  import SlidesEditorCanvas from './SlidesEditorCanvas.svelte';
  import SlidesEditorToolbar from './SlidesEditorToolbar.svelte';
  import SlidesEditorStrip from './SlidesEditorStrip.svelte';
  import { getTemplate, placeElements } from './slidesTemplates';
  import { escapeInlineText } from './slidesEditorText';
  import { effectiveTextStyle, isTypingTarget, toRenderSlide, type CanvasBox } from './slidesEditorView';
  import {
    applyDeckOperation,
    closeDeckDocument,
    deckToMarkup,
    openDeckDocument,
    redoDeck,
    undoDeck
  } from '../../../services/rustCore/deckDocument/deckDocumentClient';
  import type {
    DeckOperation,
    DeckOutcome,
    DeckTextStyle,
    DeckView
  } from '../../../services/rustCore/deckDocument/deckDocumentTypes';

  interface Props {
    /** Normalised slides markup to edit (what the embed stores). */
    markup: string;
    /** Done with changes: the core's markup of the edited deck. */
    onSave: (markup: string) => void;
    /** Leaves edit mode (after `onSave` when the deck changed). */
    onExit: () => void;
    /** Slide to open first (defaults to the first slide). */
    initialSlideId?: string;
    /** Element to select first (preview and test states). */
    initialElementId?: string;
  }

  let { markup, onSave, onExit, initialSlideId, initialElementId }: Props = $props();

  /** Arrow-key step in canvas units (Shift: larger). */
  const NUDGE = 10;
  const NUDGE_LARGE = 50;
  const NEW_TEXT_BOX = { x: 160, y: 160, w: 800, h: 160 };

  let handle: number | null = null;
  let destroyed = false;
  let view = $state<DeckView | null>(null);
  let status = $state<'loading' | 'ready' | 'error'>('loading');
  let errorCode = $state('');
  let changeError = $state('');
  let currentId = $state('');
  let selectedId = $state<string | null>(null);
  let typingId = $state<string | null>(null);
  let finishing = $state(false);
  /** Operations run one after another so the core sees them in the user's order. */
  let queue: Promise<unknown> = Promise.resolve();

  let slides = $derived(view?.slides ?? []);
  let current = $derived(slides.find((slide) => slide.id === currentId) ?? slides[0] ?? null);
  let template = $derived(getTemplate(view?.template ?? ''));
  /** The deck differs from what was opened exactly when the core has an undo step. */
  let dirty = $derived(view?.can_undo ?? false);
  let placedCurrent = $derived(
    current && view ? placeElements(toRenderSlide(current), template, view.canvas_height) : []
  );
  let selectedEntry = $derived(placedCurrent.find((entry) => entry.element.id === selectedId) ?? null);
  let selectedTextStyle = $derived(selectedEntry ? effectiveTextStyle(selectedEntry, template) : null);
  /** Paint-order position of the selection in the core's element order (-1: none). */
  let selectedOrder = $derived(
    selectedId && current ? current.elements.findIndex((element) => element.id === selectedId) : -1
  );
  let selectedColor = $derived(
    selectedId && current ? current.elements.find((element) => element.id === selectedId)?.attributes.color ?? null : null
  );

  // Selection and the open slide follow the core: an undo can remove either.
  $effect(() => {
    if (!view) return;
    if (!slides.some((slide) => slide.id === currentId)) currentId = slides[0]?.id ?? '';
    if (selectedId && !current?.elements.some((element) => element.id === selectedId)) selectedId = null;
    if (typingId && !current?.elements.some((element) => element.id === typingId)) typingId = null;
  });

  onMount(() => {
    void openDeckDocument(markup).then(
      (opened) => {
        if (destroyed) {
          void closeDeckDocument(opened.handle);
          return;
        }
        handle = opened.handle;
        view = opened.view;
        const first = opened.view.slides.find((slide) => slide.id === initialSlideId) ?? opened.view.slides[0];
        currentId = first?.id ?? '';
        if (initialElementId && first?.elements.some((element) => element.id === initialElementId)) {
          selectedId = initialElementId;
        }
        status = 'ready';
      },
      (error: unknown) => {
        errorCode = (error as { code?: string })?.code ?? String(error);
        status = 'error';
      }
    );
  });

  onDestroy(() => {
    destroyed = true;
    const open = handle;
    handle = null;
    if (open !== null) void queue.finally(() => closeDeckDocument(open));
  });

  /** Queues one core call; its view replaces ours. A refusal is shown, never swallowed. */
  function run<T extends { view: DeckView }>(call: (open: number) => Promise<T>): Promise<T | null> {
    const next = queue.then(async () => {
      if (handle === null) return null;
      try {
        const result = await call(handle);
        if (!destroyed) {
          view = result.view;
          changeError = '';
        }
        return result;
      } catch (error) {
        changeError = (error as { code?: string })?.code ?? String(error);
        console.error('[SlidesEditor] Core refused the change:', error);
        return null;
      }
    });
    queue = next;
    return next;
  }

  function apply(operation: DeckOperation): Promise<DeckOutcome | null> {
    return run((open) => applyDeckOperation(open, operation)).then((result) => result?.outcome ?? null);
  }

  function undo() {
    typingId = null;
    void run(undoDeck);
  }

  function redo() {
    typingId = null;
    void run(redoDeck);
  }

  function select(elementId: string | null) {
    if (typingId && typingId !== elementId) typingId = null;
    selectedId = elementId;
  }

  async function setGeometry(elementId: string, box: CanvasBox): Promise<void> {
    if (!current) return;
    await apply({ op: 'set_geometry', slide_id: current.id, element_id: elementId, ...box });
  }

  function startTyping(elementId: string) {
    selectedId = elementId;
    typingId = elementId;
  }

  function commitText(elementId: string, value: string) {
    if (typingId === elementId) typingId = null;
    const slide = current;
    if (!slide) return;
    const element = slide.elements.find((candidate) => candidate.id === elementId);
    if (!element || element.kind !== 'text') return;
    if (element.content.type === 'rich_text' && element.content.value === value) return;
    void apply({ op: 'set_text_content', slide_id: slide.id, element_id: elementId, markup: value });
  }

  function setStyle(style: DeckTextStyle) {
    if (!current || !selectedId) return;
    void apply({ op: 'set_text_style', slide_id: current.id, element_id: selectedId, style });
  }

  async function addText() {
    if (!current) return;
    const slideId = current.id;
    const outcome = await apply({
      op: 'add_element',
      slide_id: slideId,
      index: null,
      element: {
        kind: 'text',
        ...NEW_TEXT_BOX,
        attributes: { role: 'body' },
        content: { type: 'rich_text', value: escapeInlineText($text('embeds.slides_editor_new_text')) }
      }
    });
    if (outcome?.outcome === 'element_created' && currentId === slideId) startTyping(outcome.element_id);
  }

  function deleteSelected() {
    if (!current || !selectedId) return;
    const elementId = selectedId;
    selectedId = null;
    typingId = null;
    void apply({ op: 'delete_element', slide_id: current.id, element_id: elementId });
  }

  /** Z-order: one step to the front (+1) or the back (-1) of the slide's paint order. */
  function reorder(delta: -1 | 1) {
    if (!current || !selectedId || selectedOrder < 0) return;
    const target = selectedOrder + delta;
    if (target < 0 || target >= current.elements.length) return;
    void apply({ op: 'move_element', slide_id: current.id, element_id: selectedId, to_index: target });
  }

  function nudge(dx: number, dy: number, resize: boolean) {
    if (!current || !selectedEntry || !view) return;
    const box = selectedEntry.box;
    const next = resize
      ? { x: box.x, y: box.y, w: Math.max(1, box.w + dx), h: Math.max(1, box.h + dy) }
      : { x: Math.max(0, box.x + dx), y: Math.max(0, box.y + dy), w: box.w, h: box.h };
    void setGeometry(selectedEntry.element.id, next);
  }

  function openSlide(slideId: string) {
    typingId = null;
    selectedId = null;
    currentId = slideId;
  }

  async function addSlide() {
    const position = current ? slides.indexOf(current) + 1 : null;
    const outcome = await apply({ op: 'add_slide', index: position, layout: null });
    if (outcome?.outcome === 'slide_created') openSlide(outcome.slide_id);
  }

  async function duplicateSlide() {
    if (!current) return;
    const outcome = await apply({ op: 'duplicate_slide', slide_id: current.id });
    if (outcome?.outcome === 'slide_created') openSlide(outcome.slide_id);
  }

  function deleteSlide() {
    if (!current || slides.length <= 1) return;
    const position = slides.indexOf(current);
    const neighbour = slides[position + 1] ?? slides[position - 1];
    const slideId = current.id;
    void apply({ op: 'delete_slide', slide_id: slideId }).then((outcome) => {
      if (outcome && neighbour) openSlide(neighbour.id);
    });
  }

  function moveSlide(delta: -1 | 1) {
    if (!current) return;
    const target = slides.indexOf(current) + delta;
    if (target < 0 || target >= slides.length) return;
    void apply({ op: 'move_slide', slide_id: current.id, to_index: target });
  }

  // Speaker notes: a local draft while the field has focus, one operation on blur.
  let notesDraft = $state('');
  let notesFocused = $state(false);
  let notesSlideId = '';
  $effect(() => {
    const notes = current?.notes ?? '';
    // Only a new slide or new core notes reset the draft, never the blur itself.
    if (!untrack(() => notesFocused)) notesDraft = notes;
  });

  function onNotesFocus() {
    notesFocused = true;
    notesSlideId = current?.id ?? '';
  }

  function onNotesBlur() {
    notesFocused = false;
    const slide = slides.find((candidate) => candidate.id === notesSlideId);
    if (!slide || slide.notes === notesDraft.trim()) {
      notesDraft = current?.notes ?? '';
      return;
    }
    void apply({ op: 'set_speaker_notes', slide_id: slide.id, notes: notesDraft });
  }

  function onKeydown(event: KeyboardEvent) {
    if (status !== 'ready' || finishing) return;
    // Fields have their own editing and undo (the browser's).
    if (isTypingTarget(event.target)) return;
    const mod = event.metaKey || event.ctrlKey;
    const key = event.key.toLowerCase();
    if (mod && key === 'z') {
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
      return;
    }
    if (mod && key === 'y') {
      event.preventDefault();
      redo();
      return;
    }
    if (mod || !selectedId) return;
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      deleteSelected();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      selectedId = null;
    } else if (event.key.startsWith('Arrow')) {
      event.preventDefault();
      const step = event.shiftKey ? NUDGE_LARGE : NUDGE;
      const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
      const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
      nudge(dx, dy, event.altKey);
    }
  }

  async function done() {
    if (finishing) return;
    finishing = true;
    // Commit an open text box or notes field first (their blur sends the operation).
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    typingId = null;
    await queue;
    const open = handle;
    if (open !== null && dirty) {
      try {
        onSave(await deckToMarkup(open));
      } catch (error) {
        changeError = (error as { code?: string })?.code ?? String(error);
        console.error('[SlidesEditor] Could not read the edited deck:', error);
        finishing = false;
        return;
      }
    }
    onExit();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div
  class="slides-editor"
  data-testid="slides-editor"
  data-status={status}
  data-dirty={dirty ? 'true' : 'false'}
  data-slide-id={current?.id ?? ''}
>
  <div class="slides-editor-header">
    <span class="slides-editor-title">{$text('embeds.slides_editor_title')}</span>
    <button type="button" class="slides-editor-done" data-testid="slides-editor-done" disabled={finishing} onclick={done}>
      {$text('common.done')}
    </button>
  </div>

  {#if status === 'loading'}
    <p class="slides-editor-message" role="status" data-testid="slides-editor-loading">{$text('embeds.slides_editor_loading')}</p>
  {:else if status === 'error'}
    <p class="slides-editor-message" role="alert" data-testid="slides-editor-unavailable" data-code={errorCode}>
      {$text('embeds.slides_editor_unavailable')}
    </p>
  {:else if view && current}
    <SlidesEditorToolbar
      canUndo={view.can_undo}
      canRedo={view.can_redo}
      hasSelection={selectedId !== null}
      canForward={selectedOrder >= 0 && selectedOrder < current.elements.length - 1}
      canBackward={selectedOrder > 0}
      textStyle={selectedTextStyle}
      colorValue={selectedColor}
      {template}
      onUndo={undo}
      onRedo={redo}
      onAddText={addText}
      onDelete={deleteSelected}
      onForward={() => reorder(1)}
      onBackward={() => reorder(-1)}
      onStyle={setStyle}
    />

    {#if changeError}
      <p class="slides-editor-message slides-editor-error" role="alert" data-testid="slides-editor-change-error" data-code={changeError}>
        {$text('embeds.slides_editor_change_failed')}
      </p>
    {/if}

    <SlidesEditorCanvas
      slide={current}
      width={view.canvas_width}
      height={view.canvas_height}
      template={view.template}
      {selectedId}
      {typingId}
      onSelect={select}
      onGeometry={setGeometry}
      onStartTyping={startTyping}
      onCommitText={commitText}
    />

    <label class="slides-editor-notes">
      <span class="slides-editor-notes-label">{$text('embeds.slides_speaker_notes')}</span>
      <textarea
        rows="3"
        maxlength="5000"
        placeholder={$text('embeds.slides_editor_notes_placeholder')}
        data-testid="slides-editor-notes"
        bind:value={notesDraft}
        onfocus={onNotesFocus}
        onblur={onNotesBlur}
      ></textarea>
    </label>

    <SlidesEditorStrip
      {slides}
      width={view.canvas_width}
      height={view.canvas_height}
      template={view.template}
      currentId={current.id}
      onOpen={openSlide}
      onAdd={addSlide}
      onDuplicate={duplicateSlide}
      onDelete={deleteSlide}
      onMove={moveSlide}
    />
  {/if}
</div>

<style>
  .slides-editor {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    width: 100%;
    max-width: 100%;
    min-width: 0;
    box-sizing: border-box;
  }

  .slides-editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-4);
  }

  .slides-editor-title {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    font-weight: 600;
  }

  /* Reset of the global button sizing (buttons.css). */
  .slides-editor-done {
    min-width: 0;
    min-height: 36px;
    height: auto;
    margin: 0;
    padding: var(--spacing-2) var(--spacing-8);
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-button-primary);
    color: var(--color-grey-0);
    font-size: var(--font-size-small);
    cursor: pointer;
    transform: none;
  }

  .slides-editor-done:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  .slides-editor-done:disabled {
    opacity: 0.6;
    cursor: default;
  }

  .slides-editor-message {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .slides-editor-error {
    color: var(--color-error);
  }

  .slides-editor-notes {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    width: 100%;
  }

  .slides-editor-notes-label {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .slides-editor-notes textarea {
    width: 100%;
    box-sizing: border-box;
    margin: 0;
    padding: var(--spacing-4);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
    font-size: var(--font-size-small);
    resize: vertical;
  }

  .slides-editor-notes textarea:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 1px;
  }
</style>
