<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import { piiVisibilityStore } from '../stores/piiVisibilityStore';
  import { restorePIIInText } from './enter_message/services/piiDetectionService';
  import { timelinePreviewText, type TimelineEntry, type TimelinePreview } from '../utils/chatTimeline';
  import MessageBookmarkButton from './MessageBookmarkButton.svelte';

  let { entries, contextKey, compressionBoundary, currentId, catalogueLoading, catalogueIncomplete,
    onPreview, onActivate, onLoadEarlier, onLatest, historical, bookmarkedIds = new Set<string>(), onToggleBookmark } : {
    entries: TimelineEntry[];
    contextKey: string;
    compressionBoundary: number | null;
    currentId: string | null;
    catalogueLoading: boolean;
    catalogueIncomplete: boolean;
    historical: boolean;
    onPreview: (entry: TimelineEntry) => Promise<TimelinePreview>;
    onActivate: (entry: TimelineEntry) => Promise<void>;
    onLoadEarlier: () => void;
    onLatest: () => void;
    bookmarkedIds?: ReadonlySet<string>;
    onToggleBookmark?: (messageId: string) => Promise<void>;
  } = $props();

  let host = $state<HTMLDivElement>(undefined!);
  let rail = $state<HTMLButtonElement>(undefined!);
  let card = $state<HTMLDivElement>(undefined!);
  let selectedId = $state<string | null>(null);
  let preview = $state<TimelinePreview | null>(null);
  let loading = $state(false);
  let failed = $state(false);
  let committing = $state(false);
  let anchorY = $state(150);
  let height = $state(600);
  let cardHeight = $state(240);
  let pointerId: number | null = null;
  let touchStartY = 0;
  let pointerY = 0;
  let held = false;
  let ignoreClick = false;
  let revision = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let dismissTimer: ReturnType<typeof setTimeout> | undefined;

  const selectedIndex = $derived(entries.findIndex(entry => entry.message_id === selectedId));
  const selected = $derived(selectedIndex >= 0 ? entries[selectedIndex] : null);
  const currentIndex = $derived(entries.findIndex(entry => entry.message_id === currentId));
  const marks = $derived.by(() => {
    const count = Math.min(entries.length, 48);
    return Array.from({ length: count }, (_, i) => {
      const start = Math.floor(i * entries.length / count);
      const end = Math.floor((i + 1) * entries.length / count);
      let saved = -1;
      for (let index = start; index < end; index++) if (entries[index].bookmarked) { saved = index; break; }
      const index = saved >= 0 ? saved : count === 1 ? 0 : Math.min(end - 1, Math.max(start, Math.round(i * (entries.length - 1) / (count - 1))));
      return { entry: entries[index], index, top: entries.length === 1 ? 50 : 100 * index / (entries.length - 1) };
    });
  });
  const cardTop = $derived(Math.max(8, Math.min(anchorY - cardHeight / 2, height - cardHeight - 8)));
  const revealed = $derived(!!preview && ($piiVisibilityStore.get(preview.user.chat_id) ?? false));
  const mappings = $derived(preview ? [...(preview.user.pii_mappings ?? []), ...(preview.assistant?.pii_mappings ?? [])] : []);
  const userText = $derived(preview ? displayText(timelinePreviewText(preview.user)) : '');
  const userTitle = $derived(userText.split(/\r?\n/).find(line => line.trim())?.trim() ?? '');
  const assistantText = $derived(preview?.assistant ? displayText(timelinePreviewText(preview.assistant)) : '');

  function displayText(value: string): string {
    return revealed ? restorePIIInText(value, mappings) : value;
  }

  function dismiss(): void {
    clearTimeout(timer);
    clearTimeout(dismissTimer);
    revision++;
    selectedId = null;
    preview = null;
    loading = false;
    failed = false;
  }

  $effect.pre(() => {
    void contextKey;
    cancel();
    committing = false;
    ignoreClick = false;
  });
  $effect(() => {
    if (!card) return;
    const observer = new ResizeObserver(() => { cardHeight = card.offsetHeight; });
    observer.observe(card);
    return () => observer.disconnect();
  });
  onMount(() => {
    const observer = new ResizeObserver(() => { height = host.clientHeight; });
    observer.observe(host);
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || selectedId === null) return;
      event.preventDefault();
      // The preview has focusable bookmark/retry controls as well as the rail.
      if (card?.contains(document.activeElement)) rail.focus();
      dismiss();
    };
    window.addEventListener('keydown', escape, true);
    return () => { observer.disconnect(); window.removeEventListener('keydown', escape, true); };
  });
  onDestroy(() => { clearTimeout(timer); clearTimeout(dismissTimer); revision++; });

  function indexAt(y: number): number {
    const rect = rail.getBoundingClientRect();
    const saved = marks.filter(mark => mark.entry.bookmarked)
      .map(mark => ({ index: mark.index, distance: Math.abs(y - (rect.top + rect.height * mark.top / 100)) }))
      .sort((a, b) => a.distance - b.distance)[0];
    if (saved && saved.distance <= 5) return saved.index;
    return Math.max(0, Math.min(entries.length - 1, Math.round((y - rect.top) / rect.height * (entries.length - 1))));
  }

  function select(index: number, y?: number): void {
    clearTimeout(dismissTimer);
    const entry = entries[index];
    if (!entry) return;
    anchorY = y === undefined
      ? rail.offsetTop + (entries.length === 1 ? rail.clientHeight / 2 : index / (entries.length - 1) * rail.clientHeight)
      : y - host.getBoundingClientRect().top;
    if (selectedId === entry.message_id && !failed) return;
    clearTimeout(timer);
    selectedId = entry.message_id;
    preview = null;
    failed = false;
    loading = true;
    const request = ++revision;
    // Holding a finger or moving quickly over many marks must not issue one
    // encrypted-window request per pointer event.
    timer = setTimeout(async () => {
      try {
        const result = await onPreview(entry);
        if (request === revision) { preview = result; loading = false; }
      } catch {
        if (request === revision) { failed = true; loading = false; }
      }
    }, 120);
  }

  async function activate(): Promise<void> {
    if (!selected || committing) return;
    const entry = selected;
    const scope = contextKey;
    clearTimeout(timer);
    committing = true;
    loading = true;
    failed = false;
    try {
      await onActivate(entry);
      if (scope === contextKey) dismiss();
    } catch {
      if (scope === contextKey) { failed = true; loading = false; }
    } finally { if (scope === contextKey) committing = false; }
  }

  function pointerDown(event: PointerEvent): void {
    if (event.button !== 0 || !event.isPrimary) return;
    clearTimeout(dismissTimer);
    pointerY = event.clientY;
    if (event.pointerType === 'mouse') {
      ignoreClick = false;
      if (selected === null) select(indexAt(pointerY), pointerY);
      return;
    }
    clearTimeout(timer);
    pointerId = event.pointerId;
    touchStartY = event.clientY;
    held = false;
    rail.setPointerCapture(event.pointerId);
    timer = setTimeout(() => { held = true; select(indexAt(pointerY), pointerY); }, 280);
  }

  function pointerMove(event: PointerEvent): void {
    pointerY = event.clientY;
    if (event.pointerType === 'mouse' || (pointerId === event.pointerId && held)) select(indexAt(pointerY), pointerY);
  }

  function pointerUp(event: PointerEvent): void {
    if (pointerId !== event.pointerId) return;
    clearTimeout(timer);
    ignoreClick = true;
    if (held) {
      // Catalogue pages or a new turn can move marks while the finger rests.
      // Commit the exchange actually previewed, rather than reindexing it.
      void activate();
    } else if (Math.abs(event.clientY - touchStartY) < 10) {
      select(indexAt(event.clientY), event.clientY);
      void activate();
    } else dismiss();
    pointerId = null;
    held = false;
  }

  function cancel(): void { pointerId = null; held = false; dismiss(); }
  function scheduleHoverDismiss(event: PointerEvent): void {
    if (event.pointerType !== 'mouse' || pointerId !== null || committing) return;
    clearTimeout(dismissTimer);
    dismissTimer = setTimeout(() => { if (pointerId === null && !committing) dismiss(); }, 200);
  }
  function keydown(event: KeyboardEvent): void {
    const index = selectedIndex >= 0 ? selectedIndex : Math.max(0, currentIndex >= 0 ? currentIndex : entries.length - 1);
    let target: number | undefined;
    if (event.key === 'ArrowUp') target = Math.max(0, index - 1);
    if (event.key === 'ArrowDown') target = Math.min(entries.length - 1, index + 1);
    if (event.key === 'Home') target = 0;
    if (event.key === 'End') target = entries.length - 1;
    if (target !== undefined) { event.preventDefault(); select(target); }
    else if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); void activate(); }
  }
</script>

<div class="timeline-overlay" bind:this={host} data-testid="chat-message-timeline">
  {#if entries.length > 0}
    <button class="timeline-rail" bind:this={rail} type="button" role="slider"
      aria-label={$text('chat.timeline.navigation')} aria-orientation="vertical"
      aria-valuemin={1} aria-valuemax={entries.length} aria-valuenow={Math.max(1, selectedIndex + 1 || currentIndex + 1)}
      aria-valuetext={`${$text('chat.timeline.exchange')} ${Math.max(1, selectedIndex + 1 || currentIndex + 1)} / ${entries.length}`}
      data-testid="timeline-rail" data-count={entries.length}
      onpointerdown={pointerDown} onpointermove={pointerMove} onpointerup={pointerUp} onpointercancel={cancel}
      onpointerleave={scheduleHoverDismiss}
      onfocus={() => { if (selectedId === null && pointerId === null) select(Math.max(0, currentIndex >= 0 ? currentIndex : entries.length - 1)); }}
      onblur={(event) => { if (pointerId === null && !committing && !card?.contains(event.relatedTarget as Node)) dismiss(); }}
      onkeydown={keydown} onclick={() => { if (ignoreClick) { ignoreClick = false; return; } void activate(); }}>
      {#each marks as mark (mark.entry.message_id)}
        <span class="timeline-mark" class:compressed={compressionBoundary !== null && mark.entry.created_at <= compressionBoundary}
          class:bookmarked={!!mark.entry.bookmarked} data-message-id={mark.entry.message_id}
          style:top={`${mark.top}%`} aria-hidden="true"></span>
      {/each}
      {#if currentIndex >= 0}
        <span class="timeline-mark current" class:bookmarked={!!entries[currentIndex].bookmarked} class:compressed={compressionBoundary !== null && entries[currentIndex].created_at <= compressionBoundary}
          style:top={`${entries.length === 1 ? 50 : currentIndex / (entries.length - 1) * 100}%`} aria-hidden="true"></span>
      {/if}
      {#if selectedIndex >= 0}
        <span class="timeline-mark selected" class:bookmarked={!!selected?.bookmarked} style:top={`${entries.length === 1 ? 50 : selectedIndex / (entries.length - 1) * 100}%`} aria-hidden="true"></span>
      {/if}
    </button>
  {/if}
  {#if catalogueIncomplete || catalogueLoading}
    <button type="button" class="catalogue-action" data-testid="timeline-load-earlier" disabled={catalogueLoading}
      aria-label={$text(catalogueLoading ? 'chat.timeline.loading' : 'chat.timeline.load_earlier')}
      title={$text(catalogueLoading ? 'chat.timeline.loading' : 'chat.timeline.load_earlier')} onclick={onLoadEarlier}>···</button>
  {/if}
  {#if historical}
    <button class="latest-action" type="button" data-testid="timeline-latest" onclick={onLatest}>{$text('chat.timeline.latest')}</button>
  {/if}
  {#if selected}
    <div class="timeline-preview" bind:this={card} style:top={`${cardTop}px`} data-testid="timeline-preview"
      onpointerenter={() => clearTimeout(dismissTimer)}
      onpointerleave={scheduleHoverDismiss}
      data-message-id={selected.message_id} role="status" aria-live="polite">
      {#if failed}
        <p>{$text('chat.timeline.unavailable')}</p>
        <button type="button" data-testid="timeline-retry" onclick={() => void activate()}>{$text('chat.timeline.retry')}</button>
      {:else if loading}
        <p>{$text('chat.timeline.loading')}</p>
      {:else if preview}
        <div class="preview-heading">
          <p class="preview-user" data-testid="timeline-user-preview">{userTitle || $text('chat.timeline.attachment')}</p>
          {#if onToggleBookmark}
            {#key selected.message_id}
              <MessageBookmarkButton active={bookmarkedIds.has(selected.message_id)} question
                onToggle={() => onToggleBookmark!(selected!.message_id)} />
            {/key}
          {/if}
        </div>
        <p class="preview-response" data-testid="timeline-response-preview">{preview.assistant ? assistantText || $text('chat.timeline.attachment') : $text(preview.pending ? 'chat.timeline.pending' : 'chat.timeline.no_response')}</p>
      {/if}
      {#if compressionBoundary !== null && selected.created_at <= compressionBoundary}
        <div class="compression-label" data-testid="timeline-before-compression">{$text('chat.timeline.before_compression')}</div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .timeline-overlay { position: absolute; inset: 0; pointer-events: none; z-index: var(--z-index-dropdown, 100); }
  .timeline-rail { position: absolute; left: 0; top: max(76px, 18%); bottom: max(80px, 18%); width: 44px; min-width: 0; height: auto; min-height: 80px; margin: 0; border: 0; padding: 0; background: transparent; touch-action: none; user-select: none; -webkit-user-select: none; pointer-events: auto; cursor: pointer; border-radius: var(--border-radius-small); }
  .timeline-rail, .timeline-rail:is(:hover, :active, :focus), .catalogue-action, .catalogue-action:is(:hover, :active, :focus) { transform: none; scale: 1; filter: none; box-shadow: none; transition: none; }
  .timeline-rail:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: -3px; }
  .timeline-mark { position: absolute; left: var(--spacing-6); width: var(--spacing-6); height: 2px; transform: translateY(-50%); border-radius: 2px; background: var(--color-font-tertiary); transition: width var(--transition-fast, 150ms), background var(--transition-fast, 150ms); }
  .timeline-mark.compressed { opacity: 0.4; }
  .timeline-mark.current { width: var(--spacing-10); background: var(--color-font-primary); }
  .timeline-mark.selected { width: var(--spacing-16); background: var(--color-button-primary); }
  .timeline-mark.bookmarked { background: var(--color-highlight-yellow-solid); opacity: 1; box-shadow: 0 0 5px var(--color-highlight-yellow); }
  .timeline-preview { position: absolute; left: 80px; width: min(420px, calc(100% - 96px)); max-height: calc(100% - 16px); overflow: auto; box-sizing: border-box; padding: var(--spacing-6); color: var(--color-font-primary); background: var(--color-grey-0); border: 1px solid var(--color-grey-30); border-radius: var(--radius-7); box-shadow: var(--shadow-lg); pointer-events: auto; font-size: var(--font-size-small); }
  :global([data-theme="dark"]) .timeline-preview { background: var(--color-grey-30); border-color: var(--color-grey-40); }
  .preview-heading { display: flex; align-items: center; gap: var(--spacing-4); min-width: 0; }
  .preview-user { flex: 1; min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.5; font-weight: 500; color: var(--color-font-primary); }
  .preview-response { margin: var(--spacing-3) 0 0; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-clamp: 3; overflow: hidden; overflow-wrap: anywhere; line-height: 1.5; white-space: pre-line; font-weight: 400; color: var(--color-grey-70); }
  .compression-label { color: var(--color-font-tertiary); font-size: var(--font-size-xs); margin-top: var(--spacing-3); line-height: 1.3; }
  .catalogue-action { position: absolute; left: 0; top: max(24px, calc(18% - 44px)); width: 44px; min-width: 0; height: 44px; margin: 0; border: none; background: transparent; color: var(--color-font-tertiary); pointer-events: auto; }
  .latest-action { position: absolute; left: var(--spacing-6); bottom: var(--spacing-8); border: 1px solid var(--color-grey-30); border-radius: var(--border-radius-medium); padding: var(--spacing-4) var(--spacing-6); background: var(--color-grey-0); color: var(--color-font-primary); pointer-events: auto; font-size: var(--font-size-small); }
  @media (prefers-reduced-motion: reduce) { .timeline-mark { transition: none; } }
</style>
