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
  import { normalizeRenderedText } from '../utils/messageHighlights';

  interface Props {
    /** The element whose text nodes host the rendered message. */
    contentRoot: HTMLElement | null;
    /** Raw markdown source — used for source offset ↔ rendered character mapping. */
    rawSource: string;
    /** Highlights to render. */
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
    rawSource,
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
   * Walk the DOM text nodes inside `root`, build a rendered-char → text-node
   * offset map, then locate each highlight's rendered substring and return
   * its Range. Returns null if the highlight's source text can't be matched
   * inside the rendered DOM (e.g. markdown was rewritten on render).
   */
  function rangeForHighlight(
    root: HTMLElement,
    highlight: Extract<MessageHighlight, { kind: 'text' }>,
  ): Range | null {
    // 1. Extract the substring we need from raw source using the offsets.
    const sub = rawSource.slice(highlight.start, highlight.end);
    if (!sub) return null;

    // 2. Walk text nodes, accumulate normalized rendered text + offsets.
    const textNodes: Text[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node: Node | null = walker.nextNode();
    const nodeStarts: number[] = [];
    let rendered = '';
    while (node) {
      const t = node as Text;
      const chunk = t.nodeValue ?? '';
      nodeStarts.push(rendered.length);
      rendered += chunk;
      textNodes.push(t);
      node = walker.nextNode();
    }
    if (rendered.length === 0) return null;

    // 3. Locate the normalized version of the substring in the normalized
    //    rendered text; then back-project the match position to pre-normalised
    //    rendered coordinates by a best-effort substring search on the raw
    //    rendered string (which is what we'll Range against).
    const renderedNorm = normalizeRenderedText(rendered);
    const subNorm = normalizeRenderedText(sub).trim();
    if (!subNorm) return null;

    // Look up occurrence in the unnormalised rendered text. When rendering
    // strips asterisks / brackets, we fall back to matching on subNorm within
    // renderedNorm and then walking forward in rendered to land on a real
    // text-node offset.
    let matchInRendered = rendered.indexOf(sub);
    let matchLen = sub.length;
    if (matchInRendered === -1) {
      // Try normalised match.
      const idx = renderedNorm.indexOf(subNorm);
      if (idx === -1) return null;
      // Map the normalised offset back to the rendered offset approximately —
      // it's the same position because normalizeRenderedText only collapses
      // runs of whitespace (no insertions/deletions beyond that).
      matchInRendered = idx;
      matchLen = subNorm.length;
    }

    // 4. Convert rendered offset → (text-node, offset within node).
    function locate(renderedOffset: number): { node: Text; offset: number } | null {
      for (let i = 0; i < textNodes.length; i++) {
        const start = nodeStarts[i];
        const end = start + (textNodes[i].nodeValue?.length ?? 0);
        if (renderedOffset >= start && renderedOffset <= end) {
          return { node: textNodes[i], offset: renderedOffset - start };
        }
      }
      return null;
    }

    const startLoc = locate(matchInRendered);
    const endLoc = locate(matchInRendered + matchLen);
    if (!startLoc || !endLoc) return null;

    const range = document.createRange();
    try {
      range.setStart(startLoc.node, startLoc.offset);
      range.setEnd(endLoc.node, endLoc.offset);
    } catch {
      return null;
    }
    return range;
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
    void rawSource;
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
  }
  .highlight-box {
    all: unset;
    position: absolute;
    background: var(--color-highlight-yellow, rgba(255, 213, 0, 0.4));
    pointer-events: auto;
    cursor: pointer;
    border-radius: 2px;
    /* Sit behind the text so glyphs stay on top — z-index 0 is enough because
       the parent content sits on top in document order. */
    z-index: 0;
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
