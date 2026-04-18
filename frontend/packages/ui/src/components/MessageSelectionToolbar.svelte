<!--
  MessageSelectionToolbar.svelte

  A compact floating pill with two actions — Highlight and Highlight-and-
  comment — that appears just above a text selection inside a chat message.
  Same UX pattern as Medium, Notion, Apple Notes, Kindle.

  Why this exists: iOS/iPadOS (and some Android browsers) suppress the
  `contextmenu` event on long-press and instead show the native OS selection
  popup (Copy / Look up / Share…). Our custom MessageContextMenu therefore
  never opens on touch. The selection toolbar solves that by reacting to
  `document.selectionchange` — a cross-platform event — which lets touch
  users reach the highlight actions the same way desktop users do.

  Positioning is fixed-to-viewport so the toolbar survives scroll + layout
  shifts from streaming AI responses. The parent passes the selection rect;
  this component handles viewport-edge clamping and the entrance transition.
-->
<script lang="ts">
  import { fade } from 'svelte/transition';
  import { text } from '@repo/ui';

  interface Props {
    /** Show/hide the toolbar. Parent sets this based on whether a valid
     *  selection exists inside the owning message. */
    show: boolean;
    /** Bounding rect (viewport coords) of the current selection. */
    anchorRect: DOMRect | null;
    onHighlight: () => void;
    onHighlightAndComment: () => void;
  }

  let { show, anchorRect, onHighlight, onHighlightAndComment }: Props = $props();

  // Estimated dimensions — real rect read after mount for final placement.
  const TOOLBAR_W = 200;
  const TOOLBAR_H = 40;
  const GAP = 8; // distance between selection top and toolbar bottom
  const EDGE_PAD = 8;

  let el = $state<HTMLDivElement>();
  let left = $state(0);
  let top = $state(0);
  let placeBelow = $state(false);

  function recompute() {
    if (!anchorRect) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // Horizontal: centre over the selection, clamp to viewport.
    let x = anchorRect.left + anchorRect.width / 2;
    const halfW = TOOLBAR_W / 2;
    if (x - halfW < EDGE_PAD) x = EDGE_PAD + halfW;
    if (x + halfW > vw - EDGE_PAD) x = vw - EDGE_PAD - halfW;
    left = x;

    // Vertical: prefer above the selection; flip below if it would clip.
    const spaceAbove = anchorRect.top - GAP - TOOLBAR_H;
    if (spaceAbove >= EDGE_PAD) {
      top = anchorRect.top - GAP - TOOLBAR_H;
      placeBelow = false;
    } else {
      top = Math.min(vh - TOOLBAR_H - EDGE_PAD, anchorRect.bottom + GAP);
      placeBelow = true;
    }
  }

  $effect(() => {
    // Re-run whenever anchor changes or visibility flips.
    void anchorRect;
    void show;
    if (show && anchorRect) recompute();
  });

  function handle(e: MouseEvent | TouchEvent, action: 'highlight' | 'comment') {
    // Prevent the mousedown/touchstart that would collapse the selection
    // before the handler runs. pointer-events must stay enabled so the tap
    // registers at all.
    e.preventDefault();
    e.stopPropagation();
    if (action === 'highlight') onHighlight();
    else onHighlightAndComment();
  }

  /**
   * Mount the toolbar directly under `<body>` so its `position: fixed`
   * coordinates resolve against the viewport, never a transformed/contained
   * ancestor. Chat messages live deep inside `ActiveChat`/`ChatHistory`; any
   * future `transform`, `filter`, `contain: paint`, or `will-change: transform`
   * on an intermediate element would otherwise reparent the toolbar's
   * containing block and pull the popover far from the user's selection.
   */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return {
      destroy() {
        if (node.parentNode) node.parentNode.removeChild(node);
      },
    };
  }
</script>

{#if show && anchorRect}
  <div
    bind:this={el}
    use:portal
    class="msg-sel-toolbar {placeBelow ? 'below' : 'above'}"
    style="--sel-left: {left}px; --sel-top: {top}px;"
    data-testid="message-selection-toolbar"
    transition:fade={{ duration: 120 }}
    role="toolbar"
    aria-label="Highlight actions for selected text"
  >
    <button
      type="button"
      class="sel-btn"
      data-testid="message-selection-highlight"
      onmousedown={(e) => handle(e, 'highlight')}
      ontouchstart={(e) => handle(e, 'highlight')}
    >
      <span class="clickable-icon icon_quote"></span>
      <span class="sel-btn-label">{$text('chats.context_menu.highlight')}</span>
    </button>
    <div class="sel-divider" aria-hidden="true"></div>
    <button
      type="button"
      class="sel-btn"
      data-testid="message-selection-highlight-and-comment"
      onmousedown={(e) => handle(e, 'comment')}
      ontouchstart={(e) => handle(e, 'comment')}
    >
      <span class="clickable-icon icon_quote"></span>
      <span class="sel-btn-label">{$text('chats.context_menu.highlight_and_comment')}</span>
    </button>
  </div>
{/if}

<style>
  .msg-sel-toolbar {
    position: fixed;
    left: var(--sel-left);
    top: var(--sel-top);
    transform: translateX(-50%);
    display: flex;
    align-items: stretch;
    height: 40px;
    padding: 0 4px;
    background: var(--color-grey-100);
    color: var(--color-grey-0);
    border-radius: 20px;
    box-shadow: var(--shadow-md);
    z-index: var(--z-index-popover);
    /* Touch UX — prevent iOS magnifier while tapping the toolbar. */
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
    /* Arrow pointing towards the selection — pseudo-element on variant class. */
  }

  .msg-sel-toolbar.above::after {
    content: '';
    position: absolute;
    bottom: -6px;
    left: 50%;
    transform: translateX(-50%);
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 6px solid var(--color-grey-100);
  }

  .msg-sel-toolbar.below::after {
    content: '';
    position: absolute;
    top: -6px;
    left: 50%;
    transform: translateX(-50%);
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 6px solid var(--color-grey-100);
  }

  .sel-btn {
    all: unset;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 10px;
    cursor: pointer;
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: inherit;
    border-radius: 16px;
    min-width: 44px; /* iOS tap target */
    min-height: 36px;
    transition: background var(--duration-fast) var(--easing-default);
  }

  .sel-btn:hover,
  .sel-btn:active {
    background: rgba(255, 255, 255, 0.1);
  }

  .sel-btn .clickable-icon {
    width: 14px;
    height: 14px;
    background-color: var(--color-highlight-yellow-solid, #ffd500);
    flex-shrink: 0;
  }

  .sel-btn-label {
    white-space: nowrap;
  }

  .sel-divider {
    width: 1px;
    background: rgba(255, 255, 255, 0.18);
    margin: 6px 2px;
  }
</style>
