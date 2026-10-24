<script lang="ts">
  import { onMount, onDestroy, untrack } from 'svelte';
  import { fade } from 'svelte/transition';
  import { text } from '@repo/ui';
  import { piiVisibilityStore } from '../stores/piiVisibilityStore';
  import { restorePIIInText } from './enter_message/services/piiDetectionService';
  import { timelinePreviewText, type TimelineEntry, type TimelinePreview } from '../utils/chatTimeline';
  import MessageBookmarkButton from './MessageBookmarkButton.svelte';

  let { entries, answeredCount, contextKey, compressionBoundary, currentId, railLeft = 0, safeTop = 8,
    catalogueLoading, catalogueIncomplete, onPreview, onActivate, onLoadEarlier, bookmarkedIds, onToggleBookmark,
    id = undefined, pill = false, open = true }: {
    entries: TimelineEntry[]; answeredCount: number; contextKey: string; compressionBoundary: number | null;
    currentId: string | null; railLeft?: number; safeTop?: number;
    id?: string; pill?: boolean; open?: boolean;
    catalogueLoading: boolean; catalogueIncomplete: boolean;
    onPreview: (entry: TimelineEntry) => Promise<TimelinePreview>;
    onActivate: (entry: TimelineEntry) => Promise<void>;
    onLoadEarlier: () => void; bookmarkedIds: ReadonlySet<string>;
    onToggleBookmark: (assistantId: string) => Promise<void>;
  } = $props();

  const PITCH = 12;
  let host = $state<HTMLDivElement>();
  let rail = $state<HTMLDivElement>();
  let card = $state<HTMLDivElement>();
  let selectedId = $state<string | null>(null);
  let preview = $state<TimelinePreview | null>(null);
  let loading = $state(false);
  let failed = $state(false);
  let committing = $state(false);
  let anchorY = $state(150);
  let height = $state(600);
  let width = $state(600);
  let cardHeight = $state(180);
  let scrollTop = $state(0);
  let pointerId: number | null = null;
  let pointerY = 0;
  let touchStartY = 0;
  let lastTouchY = 0;
  let scrollGesture = false;
  let mouseInside = false;
  let held = false;
  let holdStarted = 0;
  let autoFrame = 0;
  let lastFrame = 0;
  let ignoreClick = false;
  let revision = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let dismissTimer: ReturnType<typeof setTimeout> | undefined;
  let previousEntries: TimelineEntry[] = [];
  let previousRail: HTMLDivElement | undefined;
  let previousScope = '';
  let previousCurrent: string | null = null;

  const selectedIndex = $derived(entries.findIndex(entry => entry.message_id === selectedId));
  const selected = $derived(selectedIndex >= 0 ? entries[selectedIndex] : null);
  const currentIndex = $derived(entries.findIndex(entry => entry.message_id === currentId));
  const pillPadding = $derived(pill ? 12 : 0);
  const railHeight = $derived(Math.min(240, entries.length * PITCH, Math.floor(Math.max(0, height - safeTop - 8 - pillPadding * 2) / PITCH) * PITCH));
  const visible = $derived(open && answeredCount >= 2 && railHeight >= 24);
  const railTop = $derived(Math.max(safeTop + pillPadding, (height - railHeight) / 2));
  const marks = $derived.by(() => {
    const start = Math.max(0, Math.floor(scrollTop / PITCH) - 2);
    const end = Math.min(entries.length, Math.ceil((scrollTop + railHeight) / PITCH) + 2);
    return entries.slice(start, end).map((entry, offset) => ({ entry, index: start + offset }));
  });
  const cardTop = $derived(Math.max(safeTop, Math.min(anchorY - cardHeight / 2, height - cardHeight - 8)));
  const cardLeft = $derived(railLeft + 80);
  const revealed = $derived(!!preview && ($piiVisibilityStore.get(preview.user.chat_id) ?? false));
  const mappings = $derived(preview ? [...(preview.user.pii_mappings ?? []), ...(preview.assistant?.pii_mappings ?? [])] : []);
  const userText = $derived(preview ? displayText(timelinePreviewText(preview.user)) : '');
  const userTitle = $derived(userText.split(/\r?\n/).find(line => line.trim())?.trim() ?? '');
  const assistantText = $derived(preview?.assistant ? displayText(timelinePreviewText(preview.assistant)) : '');

  function displayText(value: string): string { return revealed ? restorePIIInText(value, mappings) : value; }
  function setScroll(value: number): void {
    if (!rail) return;
    rail.scrollTop = value;
    scrollTop = rail.scrollTop;
  }
  function reveal(index: number): void {
    if (!rail || index < 0) return;
    const top = index * PITCH;
    if (top < rail.scrollTop) setScroll(top);
    else if (top + PITCH > rail.scrollTop + rail.clientHeight) setScroll(top + PITCH - rail.clientHeight);
  }
  function stopAutoScroll(): void { if (autoFrame) cancelAnimationFrame(autoFrame); autoFrame = 0; lastFrame = 0; }
  function dismiss(): void {
    clearTimeout(timer); clearTimeout(dismissTimer);
    revision++; selectedId = null; preview = null; loading = false; failed = false;
  }
  function cancel(): void { stopAutoScroll(); pointerId = null; held = false; scrollGesture = false; dismiss(); }

  $effect.pre(() => { void contextKey; void open; cancel(); committing = false; ignoreClick = false; });
  $effect(() => {
    const list = entries, scope = contextKey, current = currentId;
    void railHeight;
    if (!rail || !visible) return;
    untrack(() => {
      if (rail !== previousRail || scope !== previousScope || previousEntries.length === 0) {
        setScroll(Math.max(0, list.findIndex(entry => entry.message_id === current) * PITCH - railHeight / 2));
      } else {
        // Preserve the row under the pointer as catalogue pages prepend history.
        const index = Math.floor(rail!.scrollTop / PITCH);
        const anchor = previousEntries[index]?.message_id;
        const next = anchor ? list.findIndex(entry => entry.message_id === anchor) : -1;
        if (next >= 0) setScroll(rail!.scrollTop + (next - index) * PITCH);
      }
      if (current !== previousCurrent && selectedId === null && pointerId === null) reveal(list.findIndex(entry => entry.message_id === current));
      previousRail = rail; previousEntries = list; previousScope = scope; previousCurrent = current;
    });
  });
  $effect(() => {
    if (!card) return;
    const observer = new ResizeObserver(() => { if (card) cardHeight = card.offsetHeight; });
    observer.observe(card); return () => observer.disconnect();
  });
  onMount(() => {
    if (!host) return;
    const observer = new ResizeObserver(() => { if (host) { height = host.clientHeight; width = host.clientWidth; } });
    observer.observe(host);
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || selectedId === null) return;
      event.preventDefault(); event.stopPropagation();
      if (card?.contains(document.activeElement)) rail?.focus({ preventScroll: true });
      dismiss();
    };
    window.addEventListener('keydown', escape, true);
    return () => { observer.disconnect(); window.removeEventListener('keydown', escape, true); };
  });
  onDestroy(() => { stopAutoScroll(); clearTimeout(timer); clearTimeout(dismissTimer); revision++; });

  function indexAt(y: number): number {
    if (!rail) return -1;
    return Math.max(0, Math.min(entries.length - 1, Math.floor((rail.scrollTop + y - rail.getBoundingClientRect().top) / PITCH)));
  }
  function select(index: number, y?: number): void {
    clearTimeout(dismissTimer);
    const entry = entries[index];
    if (!entry || !host || !rail) return;
    if (y === undefined) reveal(index);
    anchorY = y === undefined ? rail.getBoundingClientRect().top - host.getBoundingClientRect().top + index * PITCH - rail.scrollTop + PITCH / 2
      : y - host.getBoundingClientRect().top;
    if (selectedId === entry.message_id && !failed) return;
    clearTimeout(timer); selectedId = entry.message_id; preview = null; failed = false; loading = true;
    const request = ++revision;
    timer = setTimeout(async () => {
      try {
        const result = await onPreview(entry);
        if (request === revision) { preview = result; loading = false; }
      } catch { if (request === revision) { failed = true; loading = false; } }
    }, 120);
  }
  async function activate(): Promise<void> {
    if (!selected || committing) return;
    const entry = selected, scope = contextKey;
    clearTimeout(timer); committing = true; loading = true; failed = false;
    try { await onActivate(entry); if (scope === contextKey) dismiss(); }
    catch { if (scope === contextKey) { failed = true; loading = false; } }
    finally { if (scope === contextKey) committing = false; }
  }
  function autoScroll(now: number): void {
    if (!held || pointerId === null || !rail) return;
    const rect = rail.getBoundingClientRect(), band = Math.min(24, rect.height / 3);
    const strength = pointerY < rect.top + band ? -Math.min(1, (rect.top + band - pointerY) / band)
      : pointerY > rect.bottom - band ? Math.min(1, (pointerY - rect.bottom + band) / band) : 0;
    const elapsed = Math.min(1, (now - holdStarted) / 2500);
    const speed = 48 + (Math.max(240, Math.min(30000, entries.length * PITCH / 4)) - 48) * elapsed * elapsed;
    const before = rail.scrollTop;
    setScroll(before + strength * speed * Math.min(0.05, lastFrame ? (now - lastFrame) / 1000 : 0));
    if (rail.scrollTop !== before) select(indexAt(pointerY), pointerY);
    if (strength < 0 && rail.scrollTop <= 0 && catalogueIncomplete && !catalogueLoading) onLoadEarlier();
    lastFrame = now; autoFrame = requestAnimationFrame(autoScroll);
  }
  function pointerDown(event: PointerEvent): void {
    if (event.button !== 0 || !event.isPrimary || !rail) return;
    clearTimeout(dismissTimer); pointerY = event.clientY;
    if (event.pointerType === 'mouse') { ignoreClick = false; select(indexAt(pointerY), pointerY); return; }
    dismiss(); pointerId = event.pointerId; touchStartY = lastTouchY = event.clientY; held = false; scrollGesture = false;
    rail.setPointerCapture(event.pointerId);
    timer = setTimeout(() => { held = true; holdStarted = performance.now(); select(indexAt(pointerY), pointerY); autoFrame = requestAnimationFrame(autoScroll); }, 280);
  }
  function pointerMove(event: PointerEvent): void {
    pointerY = event.clientY;
    if (event.pointerType === 'mouse') { mouseInside = true; select(indexAt(pointerY), pointerY); }
    else if (pointerId === event.pointerId) {
      if (held) select(indexAt(pointerY), pointerY);
      else {
        if (Math.abs(pointerY - touchStartY) > 8) { scrollGesture = true; clearTimeout(timer); }
        if (scrollGesture && rail) setScroll(rail.scrollTop + lastTouchY - pointerY);
        lastTouchY = pointerY;
      }
    }
  }
  function pointerUp(event: PointerEvent): void {
    if (pointerId !== event.pointerId) return;
    clearTimeout(timer); stopAutoScroll(); ignoreClick = true;
    if (held) void activate();
    else if (!scrollGesture && Math.abs(event.clientY - touchStartY) < 10) { select(indexAt(event.clientY), event.clientY); void activate(); }
    else dismiss();
    pointerId = null; held = false; scrollGesture = false;
  }
  function scheduleHoverDismiss(event: PointerEvent): void {
    if (event.currentTarget === rail) mouseInside = false;
    if (event.pointerType !== 'mouse' || pointerId !== null || committing) return;
    clearTimeout(dismissTimer); dismissTimer = setTimeout(() => { if (pointerId === null && !committing) dismiss(); }, 400);
  }
  function wheel(event: WheelEvent): void {
    if (event.deltaY < 0 && rail && rail.scrollTop <= 0 && catalogueIncomplete && !catalogueLoading) onLoadEarlier();
    requestAnimationFrame(() => { if (mouseInside && rail) select(indexAt(pointerY), pointerY); });
  }
  function keydown(event: KeyboardEvent): void {
    const index = selectedIndex >= 0 ? selectedIndex : Math.max(0, currentIndex >= 0 ? currentIndex : entries.length - 1);
    let target: number | undefined;
    if (event.key === 'ArrowUp') target = Math.max(0, index - 1);
    if (event.key === 'ArrowDown') target = Math.min(entries.length - 1, index + 1);
    if (event.key === 'Home') { target = 0; if (catalogueIncomplete && !catalogueLoading) onLoadEarlier(); }
    if (event.key === 'End') target = entries.length - 1;
    if (event.key === 'PageUp') target = Math.max(0, index - Math.max(1, Math.floor(railHeight / PITCH)));
    if (event.key === 'PageDown') target = Math.min(entries.length - 1, index + Math.max(1, Math.floor(railHeight / PITCH)));
    if (target !== undefined) { event.preventDefault(); select(target); }
    else if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); void activate(); }
  }
</script>

<div {id} class="timeline-overlay" bind:this={host} data-testid="chat-message-timeline">
  {#if visible}
    <div class="timeline-surface" class:pill inert={!open}
      style:left={`${railLeft}px`} style:top={`${railTop - pillPadding}px`}
      style:height={`${railHeight + pillPadding * 2}px`} style:padding-block={`${pillPadding}px`}
      transition:fade={{ duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 160 }}>
    <div class="timeline-rail" bind:this={rail} role="slider" tabindex="0"
      style:height={`${railHeight}px`}
      aria-label={$text('chat.timeline.navigation')} aria-orientation="vertical" aria-busy={catalogueLoading || committing}
      aria-valuemin={1} aria-valuemax={entries.length} aria-valuenow={Math.max(1, (selectedIndex >= 0 ? selectedIndex : currentIndex) + 1)}
      aria-valuetext={`${$text('chat.timeline.exchange')} ${Math.max(1, (selectedIndex >= 0 ? selectedIndex : currentIndex) + 1)} / ${entries.length}`}
      data-testid="timeline-rail" data-count={entries.length}
      onpointerdown={pointerDown} onpointermove={pointerMove} onpointerup={pointerUp} onpointercancel={cancel}
      onpointerleave={scheduleHoverDismiss} onwheel={wheel} onscroll={() => { if (rail) scrollTop = rail.scrollTop; }}
      onfocus={() => { if (selectedId === null && pointerId === null) select(Math.max(0, currentIndex >= 0 ? currentIndex : entries.length - 1)); }}
      onblur={(event) => { if (pointerId === null && !committing && !card?.contains(event.relatedTarget as Node)) dismiss(); }}
      onkeydown={keydown} onclick={() => { if (ignoreClick) { ignoreClick = false; return; } void activate(); }}>
      <div class="timeline-track" style:height={`${entries.length * PITCH}px`} aria-hidden="true">
        {#each marks as mark (mark.entry.message_id)}
          <span class="timeline-mark" class:compressed={compressionBoundary !== null && mark.entry.created_at <= compressionBoundary}
            class:bookmarked={!!mark.entry.bookmarked} class:current={mark.entry.message_id === currentId}
            class:selected={mark.entry.message_id === selectedId} data-message-id={mark.entry.message_id}
            style:top={`${mark.index * PITCH + 5}px`}></span>
        {/each}
      </div>
    </div>
    </div>
  {/if}
  {#if visible && selected}
    <div class="timeline-preview" bind:this={card} style:left={`${cardLeft}px`} style:top={`${cardTop}px`}
      style:width={`${Math.max(0, Math.min(420, width - cardLeft - 12))}px`} style:max-height={`${Math.max(0, height - safeTop - 8)}px`}
      data-testid="timeline-preview" data-message-id={selected.message_id} role="status" aria-live="polite"
      onpointerenter={() => clearTimeout(dismissTimer)} onpointerleave={scheduleHoverDismiss}>
      {#if failed}
        <p>{$text('chat.timeline.unavailable')}</p>
        <button type="button" data-testid="timeline-retry" onclick={() => void activate()}>{$text('chat.timeline.retry')}</button>
      {:else if loading}<p>{$text('chat.timeline.loading')}</p>
      {:else if preview}
        <div class="preview-heading">
          <p class="preview-user" data-testid="timeline-user-preview">{userTitle || $text('chat.timeline.attachment')}</p>
          {#if preview.assistant}
            {#key preview.assistant.message_id}
              <MessageBookmarkButton active={bookmarkedIds.has(preview.assistant.message_id)} onToggle={() => onToggleBookmark(preview!.assistant!.message_id)} />
            {/key}
          {/if}
        </div>
        <p class="preview-response" data-testid="timeline-response-preview">{preview.assistant ? assistantText || $text('chat.timeline.attachment') : $text(preview.pending ? 'chat.timeline.pending' : 'chat.timeline.no_response')}</p>
      {/if}
      {#if compressionBoundary !== null && selected.created_at <= compressionBoundary}
        <div class="compression-label" data-testid="timeline-before-compression">{$text('chat.timeline.before_compression')}</div>
      {/if}
      {#if catalogueIncomplete && !catalogueLoading}
        <button type="button" class="history-retry" data-testid="timeline-load-earlier" onclick={onLoadEarlier}>{$text('chat.timeline.load_earlier')}</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .timeline-overlay { position: absolute; inset: 0; pointer-events: none; z-index: var(--z-index-dropdown, 100); }
  .timeline-surface { position: absolute; width: 44px; box-sizing: border-box; }
  .timeline-surface.pill { background: var(--color-grey-20); border: 1px solid var(--color-grey-30); border-radius: var(--radius-full); box-shadow: var(--shadow-lg); }
  .timeline-surface[inert] { pointer-events: none; }
  .timeline-surface[inert] .timeline-rail { pointer-events: none; }
  .timeline-rail { position: relative; width: 44px; margin: 0; padding: 0; overflow-y: auto; overflow-x: hidden; scrollbar-width: none; overscroll-behavior: contain; overflow-anchor: none; touch-action: none; user-select: none; -webkit-user-select: none; pointer-events: auto; cursor: pointer; border-radius: var(--radius-2); animation: timeline-appear var(--duration-fast, 160ms) ease-out both; }
  .pill .timeline-rail { animation: none; }
  .timeline-rail::-webkit-scrollbar { display: none; }
  .timeline-rail:focus-visible { outline: 1px solid var(--color-font-tertiary); outline-offset: 2px; }
  .pill .timeline-rail:focus-visible { outline: none; }
  .pill:has(.timeline-rail:focus-visible) { outline: 1px solid var(--color-font-tertiary); outline-offset: 2px; }
  .timeline-track { position: relative; width: 100%; pointer-events: none; }
  .timeline-mark { position: absolute; left: var(--spacing-6); width: var(--spacing-6); height: 2px; border-radius: 2px; background: var(--color-font-primary); opacity: 0.35; transition: width var(--duration-fast, 160ms), opacity var(--duration-fast, 160ms); }
  .timeline-mark.compressed { opacity: 0.2; }
  .timeline-mark.current { width: var(--spacing-10); opacity: 0.65; }
  .timeline-mark.selected { width: var(--spacing-12); opacity: 1; }
  .timeline-mark.bookmarked { background: var(--color-highlight-yellow-solid); opacity: 1; box-shadow: 0 0 5px var(--color-highlight-yellow); }
  .timeline-preview { position: absolute; overflow: auto; box-sizing: border-box; padding: var(--spacing-6); color: var(--color-font-primary); background: var(--color-grey-0); border: 1px solid var(--color-grey-30); border-radius: var(--radius-7); box-shadow: var(--shadow-lg); pointer-events: auto; font-size: var(--font-size-small); }
  :global([data-theme="dark"]) .timeline-preview { background: var(--color-grey-30); border-color: var(--color-grey-40); }
  .preview-heading { display: flex; align-items: center; gap: var(--spacing-4); min-width: 0; }
  .preview-user { flex: 1; min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.5; font-weight: 500; color: var(--color-font-primary); }
  .preview-response { margin: var(--spacing-3) 0 0; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-clamp: 3; overflow: hidden; overflow-wrap: anywhere; line-height: 1.5; white-space: pre-line; font-weight: 400; color: var(--color-grey-70); }
  .compression-label { color: var(--color-font-tertiary); font-size: var(--font-size-xs); margin-top: var(--spacing-3); line-height: 1.3; }
  .history-retry { margin-top: var(--spacing-3); }
  @keyframes timeline-appear { from { opacity: 0; } to { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .timeline-rail { animation: none; } .timeline-mark { transition: none; } }
</style>
