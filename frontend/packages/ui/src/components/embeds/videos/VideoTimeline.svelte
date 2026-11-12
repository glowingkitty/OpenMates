<!--
  frontend/packages/ui/src/components/embeds/videos/VideoTimeline.svelte

  Timeline of a video: its parts in time order on a ruler, a playhead that follows
  playback, click/drag to seek, keyboard-accessible parts and, in edit mode, the
  pending edits (trimmed regions hatched, removed parts struck through). One style
  for generative and composed videos. Optional "+" buttons at the start and end of
  the track ask to extend the video.

  Used by VideoGenerateEmbedFullscreen (stored timeline) and by the legacy
  VideoCreateEmbedFullscreen/Preview (through timelineFromManifest).
  Nothing here fetches or sends; it only reports seeks, selections and extend requests.
-->

<script lang="ts">
  import { text } from '../../../i18n/translations';
  import {
    EMPTY_EDITS, formatSeconds, isRemoved, trimOf,
    type PendingEdits, type VideoPart, type VideoTimelineModel,
  } from './videoTimelineModel';

  interface Props {
    timeline: VideoTimelineModel;
    /** Current playback time in seconds (synced with the video). */
    currentTime?: number;
    /** Compact: no ruler, no track names, thinner bars (embed previews). */
    compact?: boolean;
    /** Called with the time in seconds when the user clicks or drags on the timeline. */
    onSeek?: (timeSeconds: number) => void;
    /** Parts can be selected (edit mode). */
    selectable?: boolean;
    selectedPartId?: string;
    onSelectPart?: (partId: string) => void;
    /** Pending edits drawn on the parts (edit mode). */
    edits?: PendingEdits;
    canExtendStart?: boolean;
    canExtendEnd?: boolean;
    /** Side whose extend field is open, for the pressed state of its button. */
    extendOpenSide?: 'start' | 'end' | null;
    onExtend?: (side: 'start' | 'end') => void;
  }

  let {
    timeline, currentTime = 0, compact = false, onSeek, selectable = false, selectedPartId,
    onSelectPart, edits = EMPTY_EDITS, canExtendStart = false, canExtendEnd = false,
    extendOpenSide = null, onExtend,
  }: Props = $props();

  const total = $derived(Math.max(1, timeline.durationInFrames));
  const totalSeconds = $derived(total / timeline.fps);
  const playheadPct = $derived(Math.min(Math.max(currentTime / totalSeconds, 0), 1) * 100);
  const showExtend = $derived(!compact && (canExtendStart || canExtendEnd) && !!onExtend);
  const showTrackNames = $derived(!compact && timeline.tracks.length > 1);
  const marks = $derived.by(() => {
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => totalSeconds / s <= 8) ?? 600;
    return Array.from({ length: Math.floor(totalSeconds / step) + 1 }, (_, i) => i * step);
  });
  let root: HTMLDivElement | undefined = $state();
  let dragging = false;

  function seekFromPointer(event: PointerEvent, bar: HTMLElement) {
    if (!onSeek) return;
    const rect = bar.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    onSeek(ratio * totalSeconds);
  }
  // Capture starts with the first move, not with the press: a capture taken on
  // pointerdown would retarget the click to the bar and no part could be selected.
  function onPointerDown(event: PointerEvent) {
    if (!onSeek || event.button !== 0) return;
    dragging = true;
    seekFromPointer(event, event.currentTarget as HTMLElement);
  }
  function onPointerMove(event: PointerEvent) {
    if (!dragging) return;
    const bar = event.currentTarget as HTMLElement;
    if (!bar.hasPointerCapture(event.pointerId)) bar.setPointerCapture(event.pointerId);
    seekFromPointer(event, bar);
  }
  function onPointerEnd(event: PointerEvent) {
    dragging = false;
    const bar = event.currentTarget as HTMLElement;
    if (bar.hasPointerCapture(event.pointerId)) bar.releasePointerCapture(event.pointerId);
  }

  function partLabel(part: VideoPart): string {
    const start = formatSeconds(part.from / timeline.fps);
    const end = formatSeconds((part.from + part.durationInFrames) / timeline.fps);
    return $text('embeds.video_generate.part_aria', { values: { label: part.label, start, end } });
  }
  function onPartClick(event: MouseEvent, part: VideoPart) {
    // A keyboard activation has no pointer position: move playback to the part start.
    if (event.detail === 0) onSeek?.(part.from / timeline.fps);
    if (selectable) onSelectPart?.(part.id);
  }
  function onPartKeydown(event: KeyboardEvent, parts: VideoPart[], index: number) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    const next = parts[index + (event.key === 'ArrowRight' ? 1 : -1)];
    if (!next) return;
    event.preventDefault();
    if (selectable) onSelectPart?.(next.id);
    root?.querySelector<HTMLElement>(`[data-part-id="${CSS.escape(next.id)}"]`)?.focus();
  }
  const pct = (frames: number) => (frames / total) * 100;
</script>

<div class="timeline" class:compact class:selectable class:extend-start-col={showExtend && canExtendStart} class:extend-end-col={showExtend && canExtendEnd} bind:this={root}
  data-testid="video-timeline" data-made-by={timeline.madeBy} role="group" aria-label={$text('embeds.video_generate.timeline')}>
  <div class="grid">
    {#if !compact}
      <div class="ruler">
        {#each marks as sec (sec)}
          <span class="ruler-mark" class:last={sec === marks[marks.length - 1]} style="left: {pct(sec * timeline.fps)}%">{sec}s</span>
        {/each}
      </div>
    {/if}

    {#each timeline.tracks as track, trackIndex (track.id)}
      <div class="row" class:first={trackIndex === 0} style="grid-row: {trackIndex + (compact ? 1 : 2)}">
        {#if showTrackNames}<span class="track-name" title={track.name}>{track.name}</span>{/if}
      </div>
      {#if showExtend && trackIndex === 0 && canExtendStart}
        <button type="button" class="extend extend-start" data-testid="video-timeline-extend-start"
          style="grid-row: {trackIndex + 2}" aria-expanded={extendOpenSide === 'start'}
          aria-label={$text('embeds.video_generate.extend_start')} title={$text('embeds.video_generate.extend_start')}
          onclick={() => onExtend?.('start')}>+</button>
      {/if}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="bar" class:main={trackIndex === 0} style="grid-row: {trackIndex + (compact ? 1 : 2)}" data-track-kind={track.kind}
        onpointerdown={onPointerDown} onpointermove={onPointerMove} onpointerup={onPointerEnd} onpointercancel={onPointerEnd}>
        {#each track.parts as part, index (part.id)}
          {@const trim = trimOf(edits, part.id)}
          {@const removed = isRemoved(edits, part.id)}
          {@const widthPct = pct(part.durationInFrames)}
          <button type="button" class="part kind-{part.kind} track-{track.kind}" class:selected={selectedPartId === part.id}
            class:removed class:trimmed={trim.fromStartFrames > 0 || trim.fromEndFrames > 0}
            style="left: {pct(part.from)}%; width: {widthPct}%"
            data-testid="video-timeline-part" data-part-id={part.id} data-removed={removed ? 'true' : undefined}
            aria-label={partLabel(part)} aria-pressed={selectable ? selectedPartId === part.id : undefined} title={partLabel(part)}
            onclick={(event) => onPartClick(event, part)} onkeydown={(event) => onPartKeydown(event, track.parts, index)}>
            {#if trim.fromStartFrames > 0}<span class="hatch start" style="width: {(trim.fromStartFrames / part.durationInFrames) * 100}%" data-testid="video-timeline-trim-start"></span>{/if}
            {#if trim.fromEndFrames > 0}<span class="hatch end" style="width: {(trim.fromEndFrames / part.durationInFrames) * 100}%" data-testid="video-timeline-trim-end"></span>{/if}
            {#if !compact || widthPct > 15}
              {#if widthPct >= 7}<span class="part-label">{part.label}</span>{/if}
              {#if !compact && widthPct >= 16}<span class="part-length">{formatSeconds(part.durationInFrames / timeline.fps)}</span>{/if}
            {/if}
          </button>
        {/each}
      </div>
      {#if showExtend && trackIndex === 0 && canExtendEnd}
        <button type="button" class="extend extend-end" data-testid="video-timeline-extend-end"
          style="grid-row: {trackIndex + 2}" aria-expanded={extendOpenSide === 'end'}
          aria-label={$text('embeds.video_generate.extend_end')} title={$text('embeds.video_generate.extend_end')}
          onclick={() => onExtend?.('end')}>+</button>
      {/if}
    {/each}

    <div class="playhead-layer" style="grid-row: 1 / -1" aria-hidden="true">
      <div class="playhead" style="left: {playheadPct}%" data-testid="video-timeline-playhead" data-time={currentTime.toFixed(2)}></div>
    </div>
  </div>
</div>

<style>
  .timeline { container-type: inline-size; width: 100%; user-select: none; color: var(--color-font-primary); }
  .grid {
    --label-w: 0px;
    --extend-start-w: 0px;
    --extend-end-w: 0px;
    position: relative;
    display: grid;
    grid-template-columns: var(--label-w) var(--extend-start-w) minmax(0, 1fr) var(--extend-end-w);
    column-gap: 0;
    row-gap: var(--spacing-2);
    align-items: stretch;
  }
  .timeline.extend-start-col .grid { --extend-start-w: 2.25rem; }
  .timeline.extend-end-col .grid { --extend-end-w: 2.25rem; }
  .timeline:not(.compact) .grid:has(.track-name) { --label-w: 4.5rem; }
  @container (max-width: 26rem) {
    .timeline:not(.compact) .grid:has(.track-name) { --label-w: 0px; }
    .track-name { display: none; }
    .timeline.extend-start-col .grid { --extend-start-w: 2rem; }
    .timeline.extend-end-col .grid { --extend-end-w: 2rem; }
  }

  .ruler { grid-column: 3; grid-row: 1; position: relative; height: 1.125rem; border-bottom: 1px solid var(--color-grey-30); }
  .ruler-mark {
    position: absolute; bottom: 2px; transform: translateX(-50%);
    font-size: var(--font-size-tiny); color: var(--color-font-tertiary); font-variant-numeric: tabular-nums;
  }
  .ruler-mark:first-child { transform: none; }
  .ruler-mark.last:not(:first-child) { transform: translateX(-100%); }

  .row { grid-column: 1; display: flex; align-items: center; min-width: 0; }
  .track-name {
    font-size: var(--font-size-tiny); font-weight: 500; color: var(--color-font-secondary);
    padding-right: var(--spacing-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }

  .bar {
    grid-column: 3; position: relative; height: 2.25rem; touch-action: pan-y;
    background: var(--color-grey-10); border-radius: var(--radius-3); overflow: hidden; cursor: pointer;
  }
  .bar.main { height: 2.75rem; }
  .compact .bar, .compact .bar.main { height: 1.25rem; }
  .compact .bar { cursor: default; }

  .part {
    /* The global button style sets height, margin and a drop shadow; a part is a plain block. */
    position: absolute; top: 2px; bottom: 2px; min-width: 2px; height: auto; margin: 0; filter: none; box-sizing: border-box;
    display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-2);
    padding: 0 var(--spacing-3); overflow: hidden; border: 0; border-radius: var(--radius-2);
    box-shadow: inset -2px 0 0 var(--color-grey-10), inset 2px 0 0 var(--color-grey-10);
    background: var(--color-app-videos); color: var(--color-font-button); font: inherit; font-size: var(--font-size-tiny); text-align: left;
    cursor: pointer; transition: filter 0.12s;
  }
  .part.track-text { background: var(--color-grey-30); color: var(--color-font-primary); }
  .part.track-audio { background: var(--color-grey-40); color: var(--color-font-primary); }
  .part:hover { filter: brightness(1.08); }
  .part:focus-visible { outline: 2px solid var(--color-font-primary); outline-offset: -3px; z-index: 2; }
  .part.selected { outline: 2px solid var(--color-button-primary); outline-offset: -2px; z-index: 1; }
  .compact .part { top: 1px; bottom: 1px; padding: 0 var(--spacing-2); cursor: default; }
  .part-label {
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600;
    text-shadow: 0 1px 2px color-mix(in srgb, var(--color-grey-100) 25%, transparent); position: relative;
  }
  .part.track-text .part-label, .part.track-audio .part-label { text-shadow: none; }
  .part-length { flex: none; font-variant-numeric: tabular-nums; opacity: 0.85; position: relative; }

  .part.removed { background: var(--color-grey-30); color: var(--color-font-tertiary); opacity: 0.7; }
  .part.removed .part-label { text-decoration: line-through; text-shadow: none; }
  .hatch {
    position: absolute; top: 0; bottom: 0; pointer-events: none;
    background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--color-grey-100) 60%, transparent) 0 3px, color-mix(in srgb, var(--color-grey-0) 35%, transparent) 3px 6px);
  }
  .hatch.start { left: 0; }
  .hatch.end { right: 0; }

  .extend {
    grid-column: 2; align-self: center; justify-self: center; width: 1.75rem; min-width: 0; height: 1.75rem; padding: 0; margin: 0; filter: none;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
    border: 1px solid var(--color-grey-30); background: var(--color-grey-0); color: var(--color-font-primary);
    font-size: var(--font-size-h3); line-height: 1; cursor: pointer;
  }
  .extend-end { grid-column: 4; }
  .extend:hover, .extend[aria-expanded='true'] { background: var(--color-button-primary); border-color: var(--color-button-primary); color: var(--color-font-button); }
  .extend:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }

  .playhead-layer { grid-column: 3; position: relative; pointer-events: none; z-index: 3; }
  .playhead {
    position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-0);
  }
  .playhead::before {
    content: ''; position: absolute; top: -3px; left: -4px; width: 10px; height: 10px; border-radius: 50%;
    background: var(--color-font-primary); box-shadow: 0 0 0 1px var(--color-grey-0);
  }
  @media (prefers-reduced-motion: reduce) { .part { transition: none; } }
</style>
