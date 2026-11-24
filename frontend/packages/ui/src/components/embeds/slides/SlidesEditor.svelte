<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditor.svelte

  Manual slides editor (web, single user). The deck lives in the Rust core in the
  shared Worker: the editor opens the markup as a core replica, draws the DeckView
  the core returns and sends one typed operation per change (deckDocumentClient).
  Validation, clamping, ids, undo/redo and markup output are the core's
  (live-collab.core.one-shared-model, slides.editor.direct-manipulation). This file
  keeps view state only: open slide, selection, the text box being typed in and the
  notes draft. Done hands the core's markup and deck facts to `onSave` when the
  deck changed and waits for it: while it runs the editor shows a saving state; if
  it fails the editor stays open with the edits and offers a retry (the caller
  persists the new embed version, see slidesDeckVersion.ts).
-->
<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { text } from '@repo/ui';
  import SlidesEditorCanvas from './SlidesEditorCanvas.svelte';
  import SlidesEditorToolbar from './SlidesEditorToolbar.svelte';
  import SlidesEditorStrip from './SlidesEditorStrip.svelte';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';
  import { liveItemClient } from '../../../services/live/liveItemClient';
  import type { LiveItemClient, LivePeer, LiveStatus } from '../../../services/live/liveItemTypes';
  import { deckCursor, peerMate } from '../../../services/live/liveSurface';
  import { placeElements, readThemeValue, resolveTemplate } from './slidesTemplates';
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
  import type { EditedDeck } from './slidesDeckVersion';
  import type {
    DeckOperation,
    DeckOutcome,
    DeckTextStyle,
    DeckView
  } from '../../../services/rustCore/deckDocument/deckDocumentTypes';

  interface Props {
    /** Normalised slides markup to edit (what the embed stores). */
    markup: string;
    /** Done with changes: persists the core's edited deck; a rejection keeps the editor open. */
    onSave: (deck: EditedDeck) => Promise<void>;
    /** Leaves edit mode (after `onSave` when the deck changed). */
    onExit: () => void;
    /** Slide to open first (defaults to the first slide). */
    initialSlideId?: string;
    /** Element to select first (preview and test states). */
    initialElementId?: string;
    /**
     * Show the toolbar's own Done check. The fullscreen hides it and uses its
     * header check-mark button instead (one Edit/Save button for every editable
     * embed), which calls the exported `done()`.
     */
    showDone?: boolean;
    /** True while Done commits the deck; bound by the fullscreen to show its header button busy. */
    finishing?: boolean;
    /**
     * Live collaboration (flag live_collaboration): the deck is the core's shared live item.
     * Operations go through liveApplyOp({op:'deck',operation}), the editor renders `liveView`
     * and there is no Save step (`markup` and `onSave` are unused).
     */
    liveItemId?: string;
    liveProjectId?: string;
    liveTeamId?: string;
    liveClient?: LiveItemClient;
    liveStatus?: LiveStatus;
    livePeers?: LivePeer[];
  }

  let {
    markup, onSave, onExit, initialSlideId, initialElementId, showDone = true, finishing = $bindable(false),
    liveItemId, liveProjectId, liveTeamId, liveClient = liveItemClient(), liveStatus = $bindable('saving'), livePeers = $bindable([])
  }: Props = $props();
  const liveId = untrack(() => liveItemId);
  /** Peers on the open slide / on a selected element (outlines and badges; display only). */
  let peerCursors = $derived(livePeers.map((peer) => ({ peer, cursor: deckCursor(peer) })));
  let slideBadges = $derived(
    Object.fromEntries(
      peerCursors.flatMap(({ peer, cursor }) => {
        const mate = peerMate(peer);
        return mate && cursor ? [[cursor.slide_id, mate]] : [];
      })
    )
  );
  /** Ids seen before a create operation, so the editor opens what the core added. */
  let awaitingNew: { slides: Set<string>; elements: Set<string>; slideId: string } | null = null;

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
  /** Saving the edited deck on Done: 'failed' keeps the editor open with a retry. */
  let saveState = $state<'idle' | 'saving' | 'failed'>('idle');
  /** Operations run one after another so the core sees them in the user's order. */
  let queue: Promise<unknown> = Promise.resolve();

  let slides = $derived(view?.slides ?? []);
  let current = $derived(slides.find((slide) => slide.id === currentId) ?? slides[0] ?? null);
  /** The core's DeckView gains `theme`; read it defensively until every core build has it. */
  let theme = $derived(readThemeValue((view as { theme?: unknown } | null)?.theme));
  let template = $derived(resolveTemplate(view?.template ?? '', theme));
  /** The deck differs from what was opened exactly when the core has an undo step. */
  let dirty = $derived(view?.can_undo ?? false);
  let placedCurrent = $derived(
    current && view ? placeElements(toRenderSlide(current), template, view.canvas_height) : []
  );
  let peerBoxes = $derived(
    current && view
      ? peerCursors.flatMap(({ peer, cursor }) => {
          const entry = cursor?.slide_id === current.id && cursor.element_id
            ? placedCurrent.find((placed) => placed.element.id === cursor.element_id)
            : undefined;
          return entry ? [{ peer, box: entry.box }] : [];
        })
      : []
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
    if (liveId) {
      const stops = [
        liveClient.on('liveView', (e) => {
          if (e.itemId !== liveId) return;
          const next = e.view as DeckView;
          const first = view === null;
          const pending = awaitingNew;
          view = next;
          if (first) {
            const start = next.slides.find((slide) => slide.id === initialSlideId) ?? next.slides[0];
            currentId = start?.id ?? '';
            if (initialElementId && start?.elements.some((element) => element.id === initialElementId)) selectedId = initialElementId;
            status = 'ready';
          } else if (pending) {
            awaitingNew = null;
            const slide = next.slides.find((candidate) => !pending.slides.has(candidate.id));
            if (slide) openSlide(slide.id);
            else {
              const open = next.slides.find((candidate) => candidate.id === pending.slideId);
              const added = open?.elements.find((element) => !pending.elements.has(element.id));
              if (added) startTyping(added.id);
            }
          }
        }),
        liveClient.on('livePresence', (e) => { if (e.itemId === liveId) livePeers = e.peers; }),
        liveClient.on('liveStatus', (e) => { if (e.itemId === liveId) liveStatus = e.status; })
      ];
      void liveClient.liveOpen(liveId, 'deck', liveProjectId, liveTeamId).catch((error: unknown) => {
        console.warn('[live] open failed', liveId, error);
        liveStatus = 'offline';
        errorCode = (error as { code?: string })?.code ?? String(error);
        status = 'error';
      });
      return () => {
        for (const stop of stops) stop();
        void queue.finally(() => liveClient.liveClose(liveId));
      };
    }
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
    if (liveId) return;
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

  /** Live mode: one typed op to the core; the new view arrives as `liveView`. */
  function applyLive(operation: DeckOperation): Promise<DeckOutcome | null> {
    if (operation.op === 'add_slide' || operation.op === 'duplicate_slide' || operation.op === 'add_element') {
      awaitingNew = {
        slides: new Set(slides.map((slide) => slide.id)),
        elements: new Set(current?.elements.map((element) => element.id) ?? []),
        slideId: current?.id ?? ''
      };
    }
    const next = queue.then(async () => {
      try {
        await liveClient.liveApplyOp(liveId as string, { op: 'deck', operation });
        changeError = '';
      } catch (error) {
        awaitingNew = null;
        changeError = (error as { code?: string })?.code ?? String(error);
        console.error('[SlidesEditor] Core refused the change:', error);
      }
      return null;
    });
    queue = next;
    return next;
  }

  function apply(operation: DeckOperation): Promise<DeckOutcome | null> {
    if (liveId) return applyLive(operation);
    return run((open) => applyDeckOperation(open, operation)).then((result) => result?.outcome ?? null);
  }

  function undo() {
    if (!view?.can_undo) return;
    typingId = null;
    if (liveId) {
      queue = queue.then(async () => {
        try {
          await liveClient.liveUndoLatestAssistant?.(liveId);
          changeError = '';
        } catch (error) {
          changeError = (error as { code?: string })?.code ?? String(error);
        }
      });
      return;
    }
    void run(undoDeck);
  }

  function redo() {
    if (liveId) return;
    typingId = null;
    void run(redoDeck);
  }

  function select(elementId: string | null) {
    if (typingId && typingId !== elementId) typingId = null;
    selectedId = elementId;
  }

  // Selection is shared as presence; the peers' outlines come back through `livePeers`.
  $effect(() => {
    if (!liveId || status !== 'ready' || !currentId) return;
    void liveClient.liveSetPresence(liveId, { cursor: { slide_id: currentId, element_id: selectedId } });
  });

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

  // Speaker notes: collapsed behind the notes button; a local draft while the field
  // has focus, one operation on blur.
  const notesPanelId = $props.id();
  let notesOpen = $state(false);
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

  /**
   * The slide takes the height left between the bar and the notes/strip below it,
   * in the window, so the whole editor fits without scrolling (as in the viewer).
   */
  let stageEl = $state<HTMLElement | null>(null);
  let belowEl = $state<HTMLElement | null>(null);
  let stageMaxWidth = $state('100%');
  const MIN_STAGE_HEIGHT = 160;
  const STAGE_BOTTOM_MARGIN = 24;
  /** .slides-editor-stage-wrap padding (handle room) on each side, in px. */
  const STAGE_PADDING = 12;

  function fitStage() {
    if (!stageEl || !belowEl || !view) return;
    // Layout offsets, not getBoundingClientRect: the fullscreen slides in with a transform.
    let top = 0;
    for (let node: HTMLElement | null = stageEl; node; node = node.offsetParent as HTMLElement | null) {
      top += node.offsetTop;
    }
    const available = window.innerHeight - top - belowEl.offsetHeight - STAGE_BOTTOM_MARGIN;
    const height = Math.max(available, MIN_STAGE_HEIGHT);
    const slideHeight = height - 2 * STAGE_PADDING;
    stageMaxWidth = `min(100%, ${Math.floor(slideHeight * (view.canvas_width / view.canvas_height)) + 2 * STAGE_PADDING}px)`;
  }

  $effect(() => {
    if (!stageEl || !belowEl || !view) return;
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

  /** Commit open text, save the edited deck as the next version when it changed, then leave edit mode. */
  export async function done(): Promise<void> {
    if (finishing) return;
    finishing = true;
    // Commit an open text box or notes field first (their blur sends the operation).
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    typingId = null;
    await queue;
    if (liveId) { onExit(); return; }
    const open = handle;
    if (open !== null && dirty && view) {
      let markupOut: string;
      try {
        markupOut = await deckToMarkup(open);
      } catch (error) {
        changeError = (error as { code?: string })?.code ?? String(error);
        console.error('[SlidesEditor] Could not read the edited deck:', error);
        finishing = false;
        return;
      }
      saveState = 'saving';
      try {
        await onSave({ markup: markupOut, title: view.title, aspect: view.aspect, slideCount: view.slides.length });
      } catch (error) {
        console.error('[SlidesEditor] Saving the edited deck failed:', error);
        saveState = 'failed';
        finishing = false;
        return;
      }
      saveState = 'idle';
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
  data-save-state={saveState}
  data-live={liveId ? 'true' : undefined}
  data-live-status={liveId ? liveStatus : undefined}
>
  {#snippet doneAction()}
    {#if saveState !== 'idle'}
      <!-- Saving the edited deck on Done: progress, or the failure with a retry (edits kept). -->
      <div
        class="slides-editor-save"
        class:slides-editor-error={saveState === 'failed'}
        role={saveState === 'failed' ? 'alert' : 'status'}
        data-testid={saveState === 'failed' ? 'slides-editor-save-failed' : 'slides-editor-save-status'}
      >
        {#if saveState === 'saving'}
          <span class="slides-editor-save-text">{$text('embeds.slides_editor_saving')}</span>
        {:else}
          <span class="slides-editor-save-text">{$text('embeds.slides_editor_save_failed')}</span>
          <button type="button" class="slides-editor-retry" data-testid="slides-editor-save-retry" onclick={done}>
            <span class="clickable-icon slides-editor-retry-icon" aria-hidden="true"></span>
            <span>{$text('common.retry')}</span>
          </button>
        {/if}
      </div>
    {/if}
    {#if showDone}
      <EmbedIconButton icon="check" primary label={$text('common.done')} testId="slides-editor-done" disabled={finishing} onclick={done} />
    {/if}
  {/snippet}

  {#if status === 'loading' || status === 'error'}
    <div class="slides-editor-header">
      {#if status === 'loading'}
        <p class="slides-editor-message" role="status" data-testid="slides-editor-loading">{$text('embeds.slides_editor_loading')}</p>
      {:else}
        <p class="slides-editor-message" role="alert" data-testid="slides-editor-unavailable" data-code={errorCode}>
          {$text('embeds.slides_editor_unavailable')}
        </p>
      {/if}
      <div class="slides-editor-header-end">{@render doneAction()}</div>
    </div>
  {:else if view && current}
    <SlidesEditorToolbar
      canUndo={view.can_undo}
      canRedo={!liveId && view.can_redo}
      hasSelection={selectedId !== null}
      canForward={selectedOrder >= 0 && selectedOrder < current.elements.length - 1}
      canBackward={selectedOrder > 0}
      textStyle={selectedTextStyle}
      colorValue={selectedColor}
      {template}
      {notesOpen}
      hasNotes={notesDraft.trim() !== ''}
      {notesPanelId}
      onUndo={undo}
      onRedo={redo}
      onAddText={addText}
      onDelete={deleteSelected}
      onForward={() => reorder(1)}
      onBackward={() => reorder(-1)}
      onStyle={setStyle}
      onToggleNotes={() => (notesOpen = !notesOpen)}
      end={doneAction}
    />

    {#if changeError}
      <p class="slides-editor-message slides-editor-error" role="alert" data-testid="slides-editor-change-error" data-code={changeError}>
        {$text('embeds.slides_editor_change_failed')}
      </p>
    {/if}

    <!-- Padding leaves room for the selection handles that sit outside the frame at the slide edges. -->
    <div class="slides-editor-stage-wrap" bind:this={stageEl} style:max-width={stageMaxWidth}>
      <SlidesEditorCanvas
        slide={current}
        width={view.canvas_width}
        height={view.canvas_height}
        template={view.template}
        {theme}
        {selectedId}
        {typingId}
        onSelect={select}
        onGeometry={setGeometry}
        onStartTyping={startTyping}
        onCommitText={commitText}
      />
      {#if peerBoxes.length > 0}
        <div class="slides-editor-peers" aria-hidden="true">
          {#each peerBoxes as { peer, box } (peer.user_id)}
            <div
              class="slides-editor-peer-box"
              data-testid="slides-editor-peer-selection"
              style:left="{(box.x / view.canvas_width) * 100}%"
              style:top="{(box.y / view.canvas_height) * 100}%"
              style:width="{(box.w / view.canvas_width) * 100}%"
              style:height="{(box.h / view.canvas_height) * 100}%"
              style:outline-color={peer.color}
            >
              <span class="slides-editor-peer-name" style:background={peer.color}>{peerMate(peer) ?? peer.display_name}</span>
            </div>
          {/each}
        </div>
      {/if}
    </div>

    <div class="slides-editor-below" bind:this={belowEl}>
      {#if notesOpen}
        <label class="slides-editor-notes" id={notesPanelId}>
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
      {/if}

      <SlidesEditorStrip
        {slides}
        width={view.canvas_width}
        height={view.canvas_height}
        template={view.template}
        {theme}
        currentId={current.id}
        onOpen={openSlide}
        onAdd={addSlide}
        onDuplicate={duplicateSlide}
        onDelete={deleteSlide}
        onMove={moveSlide}
        badges={slideBadges}
      />
    </div>
  {/if}
</div>

<style>
  .slides-editor {
    /* Named container: the bar switches to its phone layout by the editor's width. */
    container: slides-editor / inline-size;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-6);
    width: 100%;
    max-width: 100%;
    min-width: 0;
    box-sizing: border-box;
  }

  .slides-editor > :global(*) {
    width: 100%;
  }

  .slides-editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-4);
  }

  .slides-editor-header-end {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
  }

  .slides-editor-message {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .slides-editor-error {
    color: var(--color-error);
  }

  /* Inline beside Done: short status text, and on failure a Retry pill. */
  .slides-editor-save {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    min-width: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  .slides-editor-save-text {
    min-width: 0;
    max-width: 22ch;
    line-height: 1.25;
    text-align: end;
  }

  .slides-editor-save.slides-editor-error {
    color: var(--color-error);
  }

  /* Labelled pill of the fullscreen action language (icon + label, like the More menu entries). */
  .slides-editor-retry {
    all: unset;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    box-sizing: border-box;
    height: calc(25px + 2 * var(--spacing-4));
    padding: var(--spacing-4) var(--spacing-6) var(--spacing-4) var(--spacing-4);
    border-radius: 40px;
    background-color: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 600;
    cursor: pointer;
    transition: transform var(--duration-normal), box-shadow var(--duration-normal);
  }

  .slides-editor-retry:hover {
    transform: scale(1.08);
    box-shadow: var(--shadow-lg);
  }

  .slides-editor-retry:active {
    transform: scale(0.95);
    box-shadow: var(--shadow-xs);
  }

  .slides-editor-retry:focus-visible {
    outline: 2px solid var(--color-primary-start);
    outline-offset: 4px;
  }

  .slides-editor-retry-icon {
    width: 20px;
    height: 20px;
    -webkit-mask-image: var(--icon-url-reload);
    mask-image: var(--icon-url-reload);
  }

  /* Room for the selection handles, which sit outside the frame at the slide edges. */
  .slides-editor-stage-wrap {
    position: relative;
    box-sizing: border-box;
    padding: var(--spacing-6);
  }

  /* Peers' selected elements: same box as the canvas (inside the handle padding). */
  .slides-editor-peers {
    position: absolute;
    inset: var(--spacing-6);
    pointer-events: none;
  }

  .slides-editor-peer-box {
    position: absolute;
    box-sizing: border-box;
    outline: 2px solid;
  }

  .slides-editor-peer-name {
    position: absolute;
    top: -1.5em;
    left: 0;
    padding: 0 var(--spacing-2);
    border-radius: 3px 3px 3px 0;
    color: var(--color-font-button);
    font-size: var(--font-size-tiny);
    font-weight: 600;
    white-space: nowrap;
  }

  .slides-editor-below {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
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
    font-weight: 600;
  }

  .slides-editor-notes textarea {
    width: 100%;
    box-sizing: border-box;
    margin: 0;
    padding: var(--spacing-4) var(--spacing-6);
    border: 0;
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    color: var(--color-font-primary);
    font: inherit;
    font-size: var(--font-size-small);
    resize: vertical;
  }

  .slides-editor-notes textarea:focus-visible {
    outline: 2px solid var(--color-primary-start);
    outline-offset: 2px;
  }

  @media (prefers-reduced-motion: reduce) {
    .slides-editor-retry {
      transition: none;
    }
  }
</style>
