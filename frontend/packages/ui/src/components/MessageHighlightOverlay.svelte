<!--
  MessageHighlightOverlay.svelte

  Draws yellow highlight boxes on top of a rendered message's text nodes. The
  parent (ChatMessage) passes the rendered message element and the list of
  MessageHighlight objects. For each text-kind highlight, we resolve its
  {start, end} source offsets to a DOM Range over the rendered text, then
  render absolutely-positioned boxes for each ClientRect of that Range.

  This avoids surgery inside the TipTap editor. The only assumption is that
  the rendered text's characters appear (in order) as text nodes inside the
  container — which matches how ReadOnlyMessage renders markdown → prose.

  Embed-kind highlights are handled separately by UnifiedEmbedPreview via
  its `highlighted` prop.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import type { MessageHighlight } from '../types/chat';
  import { findAnchorInRendered } from '../utils/messageHighlights';

  interface Props {
    /** The element whose text nodes host the rendered message. */
    contentRoot: HTMLElement | null;
    /** Highlights to render. `start`/`end` on text-kind highlights are offsets
     *  into the concatenated text nodes of `contentRoot` — i.e. exactly what
     *  the user sees on screen. See ChatMessage.getRenderedTextSource for the
     *  source-of-truth rationale. */
    highlights: MessageHighlight[];
    /** Trigger recomputation: bump a counter whenever the message's DOM may
     *  have changed (re-render, font load, resize, etc.). */
    recomputeKey?: number;
    /** Id of the currently-focused highlight (from highlightNavigationStore). */
    focusedId?: string | null;
    /** Fires when the user clicks a highlight — parent opens the popover. */
    onHighlightClick?: (
      highlightId: string,
      rect: DOMRect,
    ) => void;
  }

  let {
    contentRoot,
    highlights,
    recomputeKey = 0,
    focusedId = null,
    onHighlightClick,
  }: Props = $props();

  type Box = {
    id: string;
    top: number;
    left: number;
    width: number;
    height: number;
    hasComment: boolean;
    focused: boolean;
  };

  let boxes = $state<Box[]>([]);

  /**
   * Resolve a text highlight to a DOM Range using its text-quote anchor.
   * This is the primary lookup — immune to re-render offset drift because
   * we find the matching text in the CURRENT rendered DOM every time.
   *
   * See utils/messageHighlights.ts:findAnchorInRendered for the algorithm.
   */
  function rangeForHighlight(
    root: HTMLElement,
    highlight: Extract<MessageHighlight, { kind: 'text' }>,
  ): Range | null {
    return findAnchorInRendered(root, highlight.anchor);
  }

  async function recompute() {
    await tick();
    if (!contentRoot || highlights.length === 0) {
      boxes = [];
      return;
    }
    const rootRect = contentRoot.getBoundingClientRect();
    const next: Box[] = [];
    for (const h of highlights) {
      if (h.kind !== 'text') continue;
      const range = rangeForHighlight(contentRoot, h);
      if (!range) continue;
      const rects = Array.from(range.getClientRects());
      if (!rects.length) continue;
      const focused = focusedId === h.id;
      const hasComment = !!(h.comment && h.comment.trim().length > 0);
      for (const r of rects) {
        next.push({
          id: h.id,
          top: r.top - rootRect.top,
          left: r.left - rootRect.left,
          width: r.width,
          height: r.height,
          hasComment,
          focused,
        });
      }
    }
    boxes = next;
  }

  $effect(() => {
    // Re-run whenever inputs change
    void contentRoot;
    void highlights;
    void recomputeKey;
    void focusedId;
    recompute();
  });

  /** Look up the full DOMRect of the first box for a highlight id. */
  export function getHighlightRect(id: string): DOMRect | null {
    if (!contentRoot) return null;
    const rootRect = contentRoot.getBoundingClientRect();
    const box = boxes.find((b) => b.id === id);
    if (!box) return null;
    return new DOMRect(
      rootRect.left + box.left,
      rootRect.top + box.top,
      box.width,
      box.height,
    );
  }

  function handleBoxClick(e: MouseEvent, id: string) {
    e.stopPropagation();
    e.preventDefault();
    if (!contentRoot) return;
    const rect = getHighlightRect(id);
    if (rect) onHighlightClick?.(id, rect);
  }
</script>

<div class="highlight-layer" aria-hidden="true">
  {#each boxes as box, i (i)}
    <button
      type="button"
      class="highlight-box"
      class:has-comment={box.hasComment}
      class:focused={box.focused}
      data-testid="message-highlight-box"
      data-highlight-id={box.id}
      aria-label={box.hasComment ? 'Highlight with comment' : 'Highlight'}
      style="top: {box.top}px; left: {box.left}px; width: {box.width}px; height: {box.height}px;"
      onclick={(e) => handleBoxClick(e, box.id)}
    ></button>
  {/each}
</div>

<style>
  .highlight-layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
    /* Raise the whole overlay above the rendered message content so the yellow
       boxes are hit-testable. Individual boxes re-enable pointer-events so the
       rest of the layer stays click-through (links, embed cards, mentions). */
    z-index: 2;
  }
  .highlight-box {
    all: unset;
    position: absolute;
    background: var(--color-highlight-yellow, rgba(255, 213, 0, 0.4));
    /* Yellow at 40% opacity renders on top of the text but stays readable —
       this matches standard annotation UX (Google Docs, Kindle). */
    mix-blend-mode: multiply;
    pointer-events: auto;
    cursor: pointer;
    border-radius: 2px;
  }
  .highlight-box.focused {
    outline: 2px solid var(--color-highlight-yellow-solid, #ffd500);
    outline-offset: 1px;
  }
  .highlight-box.has-comment::after {
    content: '💬';
    position: absolute;
    top: -10px;
    right: -10px;
    font-size: 12px;
    background: var(--color-highlight-yellow-solid, #ffd500);
    border-radius: 50%;
    width: 18px;
    height: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }
</style>
