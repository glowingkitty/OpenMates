<!--
  HighlightCommentPopover.svelte

  Inline popover anchored to a rendered highlight range. Two modes:
    - View  : show author + comment + (author-only) Edit / Delete buttons
    - Edit  : textarea + Save / Cancel (max 500 chars)

  The parent owns the data (passes `highlight`, `isAuthor`, and callbacks for
  `onSaveComment`, `onDelete`, `onClose`). Positioning is anchor-based: the
  parent passes an `anchorRect` (DOMRect) and the popover positions itself
  above/below and adjusts for viewport edges.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '@repo/ui';
  import type { MessageHighlight } from '../types/chat';

  interface Props {
    highlight: MessageHighlight;
    anchorRect: DOMRect | null;
    isAuthor: boolean;
    /** Start in edit mode immediately (used after "Highlight & comment"). */
    initialEditMode?: boolean;
    onSaveComment: (comment: string | undefined) => Promise<void> | void;
    onDelete: () => Promise<void> | void;
    onClose: () => void;
  }

  let {
    highlight,
    anchorRect,
    isAuthor,
    initialEditMode = false,
    onSaveComment,
    onDelete,
    onClose,
  }: Props = $props();

  const MAX_COMMENT_LEN = 500;

  let popoverEl = $state<HTMLDivElement>();
  let textareaEl = $state<HTMLTextAreaElement>();
  // Initialise to literal false / empty — the onMount block below syncs with
  // props once, AFTER the component is mounted. We intentionally do NOT use a
  // reactive $effect here: the `highlight` prop identity changes whenever the
  // store upserts (e.g. when the server-side add_message_highlight broadcast
  // comes back), and re-running the effect would wipe whatever the user had
  // typed in the textarea.
  let editing = $state(false);
  let draft = $state('');
  let saving = $state(false);

  // Position: default above the highlight; flip below if not enough room.
  let top = $state(0);
  let left = $state(0);
  let showBelow = $state(false);

  const POPOVER_WIDTH = 300;
  const POPOVER_MIN_HEIGHT = 80;

  async function recomputePosition() {
    await tick();
    if (!anchorRect) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const padding = 12;
    const height = popoverEl?.getBoundingClientRect().height ?? POPOVER_MIN_HEIGHT;

    let x = anchorRect.left + anchorRect.width / 2;
    // Clamp horizontally
    const half = POPOVER_WIDTH / 2;
    if (x + half > vw - padding) x = vw - padding - half;
    if (x - half < padding) x = padding + half;

    const spaceAbove = anchorRect.top - padding - height;
    const below = spaceAbove < padding;
    const y = below
      ? anchorRect.bottom + padding
      : anchorRect.top - padding - height;
    // Clamp vertically
    const clampedY = Math.max(padding, Math.min(vh - height - padding, y));

    left = x;
    top = clampedY;
    showBelow = below;
  }

  onMount(() => {
    // Portal the popover to document.body so `position: fixed` isn't broken
    // by ancestor `filter: drop-shadow()` on .user-message-content /
    // .mate-message-content (which creates a new containing block).
    if (popoverEl) {
      document.body.appendChild(popoverEl);
    }

    // One-shot sync with the incoming props — see the comment above the
    // declarations for why this is NOT done inside a reactive $effect.
    editing = initialEditMode;
    draft = highlight.comment ?? '';
    recomputePosition();
    if (editing) textareaEl?.focus();
    function onDocKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (editing && initialEditMode && !highlight.comment) {
          // Cancelling a brand-new "Highlight & comment" — close popover.
          onClose();
        } else if (editing) {
          // Cancel the edit, keep popover open in view mode.
          editing = false;
          draft = highlight.comment ?? '';
        } else {
          onClose();
        }
      }
    }
    function onDocClick(e: MouseEvent) {
      if (popoverEl && !popoverEl.contains(e.target as Node)) {
        onClose();
      }
    }
    function onResize() { recomputePosition(); }
    document.addEventListener('keydown', onDocKey);
    document.addEventListener('mousedown', onDocClick);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    return () => {
      document.removeEventListener('keydown', onDocKey);
      document.removeEventListener('mousedown', onDocClick);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
      // Remove the portaled element from body on cleanup
      if (popoverEl && popoverEl.parentNode === document.body) {
        document.body.removeChild(popoverEl);
      }
    };
  });

  async function handleSave() {
    if (saving) return;
    saving = true;
    const trimmed = draft.trim();
    const next = trimmed ? trimmed.slice(0, MAX_COMMENT_LEN) : undefined;
    try {
      await onSaveComment(next);
      editing = false;
    } finally {
      saving = false;
    }
  }

  function handleCancel() {
    if (initialEditMode && !highlight.comment) {
      onClose();
      return;
    }
    editing = false;
    draft = highlight.comment ?? '';
  }

  async function handleDelete() {
    if (saving) return;
    saving = true;
    try {
      await onDelete();
    } finally {
      saving = false;
    }
  }

  function initials(name: string | undefined): string {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    return (parts[0]?.[0] ?? '?').toUpperCase() + (parts[1]?.[0]?.toUpperCase() ?? '');
  }
</script>

<div
  class="highlight-popover {showBelow ? 'below' : 'above'}"
  style="--popover-left: {left}px; --popover-top: {top}px;"
  bind:this={popoverEl}
  data-testid="highlight-comment-popover"
>
  <div class="hp-header">
    <div class="hp-avatar">{initials(highlight.author_display_name)}</div>
    <div class="hp-author">{highlight.author_display_name ?? 'User'}</div>
  </div>

  {#if editing}
    <textarea
      bind:this={textareaEl}
      class="hp-textarea"
      data-testid="highlight-comment-input"
      placeholder={$text('chats.highlight.comment_placeholder')}
      maxlength={MAX_COMMENT_LEN}
      bind:value={draft}
      rows="3"
    ></textarea>
    <div class="hp-actions">
      <button type="button" class="hp-btn hp-btn-secondary" onclick={handleCancel} disabled={saving}>
        {$text('chats.highlight.cancel')}
      </button>
      <button
        type="button"
        class="hp-btn hp-btn-primary"
        data-testid="highlight-comment-save"
        onclick={handleSave}
        disabled={saving}
      >
        {$text('chats.highlight.save')}
      </button>
    </div>
  {:else}
    {#if highlight.comment}
      <div class="hp-comment" data-testid="highlight-comment-text">{highlight.comment}</div>
    {:else if isAuthor}
      <div class="hp-comment hp-comment-empty">{$text('chats.highlight.comment_placeholder')}</div>
    {/if}
    {#if isAuthor}
      <div class="hp-actions">
        <button
          type="button"
          class="hp-btn hp-btn-danger"
          data-testid="highlight-comment-delete"
          onclick={handleDelete}
          disabled={saving}
        >{$text('chats.highlight.delete')}</button>
        <button
          type="button"
          class="hp-btn hp-btn-secondary"
          data-testid="highlight-comment-edit"
          onclick={() => (editing = true)}
          disabled={saving}
        >{$text('chats.highlight.edit')}</button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .highlight-popover {
    position: fixed;
    left: var(--popover-left);
    top: var(--popover-top);
    transform: translateX(-50%);
    width: 300px;
    background: var(--color-grey-0);
    color: var(--color-grey-100);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-5);
    box-shadow: var(--shadow-md);
    padding: var(--spacing-6);
    z-index: var(--z-index-popover);
    font-size: var(--font-size-small);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }
  .hp-header { display: flex; align-items: center; gap: var(--spacing-3); }
  .hp-avatar {
    width: 28px; height: 28px;
    border-radius: 50%;
    background: var(--color-highlight-yellow-solid, #ffd500);
    color: var(--color-grey-100);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 11px;
  }
  .hp-author { font-weight: 600; }
  .hp-comment {
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.45;
  }
  .hp-comment-empty { color: var(--color-grey-60); font-style: italic; }
  .hp-textarea {
    width: 100%; box-sizing: border-box;
    min-height: 64px; max-height: 180px;
    padding: var(--spacing-3);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    font-size: var(--font-size-small); font-family: inherit;
    resize: vertical;
    background: var(--color-grey-10);
    color: var(--color-grey-100);
  }
  .hp-textarea:focus { outline: 2px solid var(--color-highlight-yellow-solid, #ffd500); outline-offset: 1px; }
  .hp-actions { display: flex; gap: var(--spacing-3); justify-content: flex-end; }
  .hp-btn {
    all: unset;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: var(--font-size-xs);
    font-weight: 600;
    cursor: pointer;
    transition: background var(--duration-fast) var(--easing-default);
  }
  .hp-btn:disabled { opacity: 0.55; cursor: default; }
  .hp-btn-primary {
    background: var(--color-highlight-yellow-solid, #ffd500);
    color: var(--color-grey-100);
  }
  .hp-btn-primary:hover:not(:disabled) { filter: brightness(0.95); }
  .hp-btn-secondary {
    background: var(--color-grey-20);
    color: var(--color-grey-100);
  }
  .hp-btn-secondary:hover:not(:disabled) { background: var(--color-grey-30); }
  .hp-btn-danger {
    background: transparent;
    color: var(--color-error, #e74c3c);
  }
  .hp-btn-danger:hover:not(:disabled) { background: rgba(231, 76, 60, 0.1); }
</style>
