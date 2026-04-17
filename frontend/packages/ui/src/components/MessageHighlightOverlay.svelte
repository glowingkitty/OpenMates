<!--
  MessageHighlightOverlay.svelte

  Applies yellow-background `<mark>` wrappers to the rendered message body for
  every text-kind highlight. Using inline marks (instead of absolutely
  positioned overlay boxes) makes highlights naturally reflow with the text
  on viewport changes, zoom, font-size shifts, and embed re-renders — the
  browser's text layout engine does the work for free.

  The component name is kept for call-site compatibility; it no longer draws
  an overlay layer. Its public surface:
    - `contentRoot`, `highlights`, `recomputeKey`, `focusedId`,
      `onHighlightClick` — unchanged from the previous box-drawing version.
    - `getHighlightRect(id)` — returns the bounding client rect of the first
      mark that renders this highlight (used to anchor the comment popover).

  Embed-kind highlights are handled separately by UnifiedEmbedPreview via
  its `highlighted` prop.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import type { MessageHighlight } from '../types/chat';
  import { findAnchorInRendered } from '../utils/messageHighlights';

  interface Props {
    /** The element whose text nodes host the rendered message body. */
    contentRoot: HTMLElement | null;
    /** Highlights to render. `anchor` is resolved against the current DOM
     *  every run so embed re-renders, streaming updates, or reflow don't
     *  stale-pin the highlight to a fixed coordinate. */
    highlights: MessageHighlight[];
    /** Trigger recomputation: bump a counter whenever the message's DOM may
     *  have changed (re-render, font load, etc.). */
    recomputeKey?: number;
    /** Id of the currently-focused highlight (from highlightNavigationStore).
     *  Adds a `.focused` class to that highlight's marks for outline styling. */
    focusedId?: string | null;
    /** Fires when the user clicks a highlight mark — parent opens the popover. */
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

  const MARK_CLASS = 'message-highlight-mark';
  const MARK_ATTR = 'data-highlight-id';
  const MARK_COMMENT_CLASS = 'has-comment';
  const MARK_FOCUSED_CLASS = 'focused';
  const EMBED_SKIP_SELECTOR = '.embed-full-width-wrapper';

  function isInsideEmbed(node: Node): boolean {
    const el = (node as Text).parentElement;
    if (!el) return false;
    return el.closest(EMBED_SKIP_SELECTOR) !== null;
  }

  /**
   * Unwrap all `<mark.message-highlight-mark>` elements inside `root`,
   * replacing each with a text node of the same content and merging
   * adjacent text nodes so repeated apply/remove cycles don't leave the
   * DOM fragmented.
   */
  function removeMarks(root: HTMLElement) {
    const marks = Array.from(root.querySelectorAll(`mark.${MARK_CLASS}`));
    for (const mark of marks) {
      const parent = mark.parentNode;
      if (!parent) continue;
      const text = document.createTextNode(mark.textContent ?? '');
      parent.replaceChild(text, mark);
      parent.normalize();
    }
  }

  /**
   * Wrap every text-node segment inside `range` in a `<mark>` with the given
   * attributes, splitting text nodes as needed when the range starts or ends
   * mid-node. Returns the list of mark elements created so callers can add
   * state classes (focused, has-comment) without a second DOM walk.
   */
  function wrapRange(
    range: Range,
    highlightId: string,
    extraClasses: string[],
  ): HTMLElement[] {
    const segments: { node: Text; start: number; end: number }[] = [];
    const ancestor = range.commonAncestorContainer;

    if (ancestor.nodeType === Node.TEXT_NODE) {
      // Both endpoints are in the same text node — TreeWalker can't descend
      // into a text node (it has no children), so handle it directly.
      const t = ancestor as Text;
      const start = range.startOffset;
      const end = range.endOffset;
      if (end > start) segments.push({ node: t, start, end });
    } else {
      const walker = document.createTreeWalker(
        ancestor,
        NodeFilter.SHOW_TEXT,
        { acceptNode(n) {
          if (isInsideEmbed(n)) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }},
      );
      let n: Node | null = walker.nextNode();
      while (n) {
        const t = n as Text;
        const nodeLen = t.length;
        if (range.intersectsNode(t)) {
          const isStart = t === range.startContainer;
          const isEnd = t === range.endContainer;
          const start = isStart ? range.startOffset : 0;
          const end = isEnd ? range.endOffset : nodeLen;
          if (end > start) segments.push({ node: t, start, end });
        }
        n = walker.nextNode();
      }
    }

    const marks: HTMLElement[] = [];
    // Wrap in reverse document order so splits in earlier nodes don't shift
    // references to later nodes (references stay valid since splitText just
    // creates siblings, but reverse order is still the defensive choice).
    for (let i = segments.length - 1; i >= 0; i--) {
      const { node, start, end } = segments[i];
      let target: Text = node;
      if (start > 0) {
        target = target.splitText(start);
      }
      const tail = end - start;
      if (tail < target.length) {
        target.splitText(tail);
      }
      const mark = document.createElement('mark');
      mark.className = [MARK_CLASS, ...extraClasses].join(' ');
      mark.setAttribute(MARK_ATTR, highlightId);
      // Keep the legacy `message-highlight-box` testid so existing Playwright
      // specs and the focused-scroll lookup in ChatHistory.svelte keep working
      // after the overlay-to-mark migration.
      mark.setAttribute('data-testid', 'message-highlight-box');
      const parent = target.parentNode;
      if (!parent) continue;
      parent.replaceChild(mark, target);
      mark.appendChild(target);
      marks.push(mark);
    }
    marks.reverse();
    return marks;
  }

  let lastClickHandler: ((e: Event) => void) | null = null;
  let lastEnterHandler: ((e: Event) => void) | null = null;
  let lastLeaveHandler: ((e: Event) => void) | null = null;

  function attachEventHandlers(root: HTMLElement) {
    if (lastClickHandler) root.removeEventListener('click', lastClickHandler);
    if (lastEnterHandler) root.removeEventListener('mouseenter', lastEnterHandler, true);
    if (lastLeaveHandler) root.removeEventListener('mouseleave', lastLeaveHandler, true);

    const clickHandler = (e: Event) => {
      const target = e.target as HTMLElement | null;
      const mark = target?.closest(`mark.${MARK_CLASS}`) as HTMLElement | null;
      if (!mark) return;
      const id = mark.getAttribute(MARK_ATTR);
      if (!id) return;
      e.stopPropagation();
      e.preventDefault();
      onHighlightClick?.(id, mark.getBoundingClientRect());
    };

    const enterHandler = (e: Event) => {
      const mark = (e.target as HTMLElement)?.closest(`mark.${MARK_CLASS}`) as HTMLElement | null;
      if (!mark) return;
      const id = mark.getAttribute(MARK_ATTR);
      if (!id) return;
      root.querySelectorAll(`mark.${MARK_CLASS}[${MARK_ATTR}="${CSS.escape(id)}"]`)
        .forEach(m => m.classList.add('hovered'));
    };

    const leaveHandler = (e: Event) => {
      const mark = (e.target as HTMLElement)?.closest(`mark.${MARK_CLASS}`) as HTMLElement | null;
      if (!mark) return;
      const id = mark.getAttribute(MARK_ATTR);
      if (!id) return;
      root.querySelectorAll(`mark.${MARK_CLASS}[${MARK_ATTR}="${CSS.escape(id)}"]`)
        .forEach(m => m.classList.remove('hovered'));
    };

    root.addEventListener('click', clickHandler);
    root.addEventListener('mouseenter', enterHandler, true);
    root.addEventListener('mouseleave', leaveHandler, true);
    lastClickHandler = clickHandler;
    lastEnterHandler = enterHandler;
    lastLeaveHandler = leaveHandler;
  }

  async function recompute() {
    await tick();
    const root = contentRoot;
    if (!root) return;
    removeMarks(root);
    if (highlights.length === 0) return;

    // Resolve every highlight first (DOM is still clean), then apply wraps
    // in reverse document order so earlier wraps don't shift later ranges.
    const resolved: { id: string; range: Range; hasComment: boolean; focused: boolean }[] = [];
    for (const h of highlights) {
      if (h.kind !== 'text') continue;
      const range = findAnchorInRendered(root, h.anchor);
      if (!range) continue;
      resolved.push({
        id: h.id,
        range,
        hasComment: !!(h.comment && h.comment.trim().length > 0),
        focused: focusedId === h.id,
      });
    }
    // Sort by range start in document order, then wrap from last to first.
    resolved.sort((a, b) => {
      const cmp = a.range.compareBoundaryPoints(Range.START_TO_START, b.range);
      return cmp;
    });
    for (let i = resolved.length - 1; i >= 0; i--) {
      const { id, range, hasComment, focused } = resolved[i];
      const extras: string[] = [];
      if (hasComment) extras.push(MARK_COMMENT_CLASS);
      if (focused) extras.push(MARK_FOCUSED_CLASS);
      try {
        wrapRange(range, id, extras);
      } catch (err) {
        console.debug('[MessageHighlightOverlay] wrapRange failed', err);
      }
    }

    attachEventHandlers(root);
  }

  $effect(() => {
    void contentRoot;
    void highlights;
    void recomputeKey;
    void focusedId;
    recompute();
    return () => {
      const root = contentRoot;
      if (root) removeMarks(root);
      if (root) {
        if (lastClickHandler) { root.removeEventListener('click', lastClickHandler); lastClickHandler = null; }
        if (lastEnterHandler) { root.removeEventListener('mouseenter', lastEnterHandler, true); lastEnterHandler = null; }
        if (lastLeaveHandler) { root.removeEventListener('mouseleave', lastLeaveHandler, true); lastLeaveHandler = null; }
      }
    };
  });

  /** Look up the bounding rect of the first mark element for `id`. */
  export function getHighlightRect(id: string): DOMRect | null {
    if (!contentRoot) return null;
    const mark = contentRoot.querySelector(
      `mark.${MARK_CLASS}[${MARK_ATTR}="${CSS.escape(id)}"]`,
    ) as HTMLElement | null;
    if (!mark) return null;
    return mark.getBoundingClientRect();
  }
</script>

<style>
  /* Marks live inside the rendered message body; style them globally so
     the color token and interactions apply wherever they land (prose
     paragraphs, list items, quoted spans, etc.). */
  :global(mark.message-highlight-mark) {
    background: var(--color-highlight-yellow, rgba(255, 213, 0, 0.4));
    /* Override the global mark rule in fonts.css which sets
       background-clip:text + -webkit-text-fill-color:transparent
       (gradient text trick for the brand logo). Without this reset
       highlight text becomes invisible behind a solid yellow block. */
    -webkit-background-clip: unset;
    background-clip: unset;
    -webkit-text-fill-color: unset;
    color: inherit;
    cursor: pointer;
    padding: 0 1px;
    transition: background var(--duration-fast, 150ms) var(--easing-default, ease);
  }
  :global(mark.message-highlight-mark.hovered) {
    background: var(--color-highlight-yellow-solid, #ffd500);
  }
  :global(mark.message-highlight-mark.focused) {
    background: rgba(255, 213, 0, 0.65);
  }
  /* Comment indicator — a small 💬 chip pinned to the trailing edge of the
     last mark for a highlight. Using ::after on every mark would show a
     chip per line for multi-line highlights; the `last-of-type` selector
     targets only the final mark node in the parent block. */
  :global(mark.message-highlight-mark.has-comment:last-of-type::after) {
    content: '💬';
    font-size: 10px;
    margin-left: 2px;
    vertical-align: super;
  }
</style>
