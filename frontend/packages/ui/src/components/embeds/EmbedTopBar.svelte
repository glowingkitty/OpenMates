<!--
  frontend/packages/ui/src/components/embeds/EmbedTopBar.svelte

  Action button row rendered at the top of every embed fullscreen view.
  Lives in normal document flow (not absolutely positioned) so the scrollable
  content area — including the gradient header banner — always starts below it.

  Layout:
  - Left side: Chat, Share, Copy, Download, Report Issue, PII toggle buttons
  - Right side: Minimize (close) button

  All buttons use the same pill-wrapper + circular-icon design as the new-chat
  button in ActiveChat.svelte.
-->

<script lang="ts">
  import { text } from '@repo/ui';

  interface Props {
    /** Whether to show the "restore chat" button (ultra-wide side-by-side mode). */
    showChatButton?: boolean;
    /** Whether to show the share button (default true). */
    showShare?: boolean;
    /** Whether to show the copy button (truthy = show). */
    showCopy?: boolean;
    /** Whether to show the download button (truthy = show). */
    showDownload?: boolean;
    /** Whether to show the PII hide/show toggle. */
    showPIIToggle?: boolean;
    /** Whether PII is currently revealed (controls toggle visual state). */
    piiRevealed?: boolean;

    onClose: () => void;
    onShare?: () => void;
    onCopy?: () => void;
    onDownload?: () => void;
    onReportIssue?: () => void;
    onShowChat?: () => void;
    onTogglePII?: () => void;
  }

  let {
    showChatButton = false,
    showShare = true,
    showCopy = false,
    showDownload = false,
    showPIIToggle = false,
    piiRevealed = false,
    onClose,
    onShare,
    onCopy,
    onDownload,
    onReportIssue,
    onShowChat,
    onTogglePII,
  }: Props = $props();
</script>

<div class="embed-top-bar">
  <!-- Left: action buttons -->
  <div class="top-bar-left">
    <!-- Restore chat (ultra-wide side-by-side mode) -->
    {#if showChatButton && onShowChat}
      <div class="button-wrapper">
        <button
          class="action-button"
          onclick={onShowChat}
          aria-label={$text('chat.show_chat')}
          title={$text('chat.show_chat')}
        >
          <span class="clickable-icon icon_chat"></span>
        </button>
      </div>
    {/if}

    <!-- Share -->
    {#if showShare}
      <div class="button-wrapper">
        <button
          class="action-button"
          onclick={onShare}
          aria-label={$text('chat.share')}
          title={$text('chat.share')}
        >
          <span class="clickable-icon icon_share"></span>
        </button>
      </div>
    {/if}

    <!-- Copy -->
    {#if showCopy && onCopy}
      <div class="button-wrapper">
        <button
          class="action-button"
          onclick={onCopy}
          aria-label="Copy"
          title="Copy"
        >
          <span class="clickable-icon icon_copy"></span>
        </button>
      </div>
    {/if}

    <!-- Download -->
    {#if showDownload && onDownload}
      <div class="button-wrapper">
        <button
          class="action-button"
          onclick={onDownload}
          aria-label="Download"
          title="Download"
        >
          <span class="clickable-icon icon_download"></span>
        </button>
      </div>
    {/if}

    <!-- Report Issue (always shown) -->
    <div class="button-wrapper">
      <button
        class="action-button"
        onclick={onReportIssue}
        aria-label={$text('header.report_issue')}
        title={$text('header.report_issue')}
      >
        <span class="clickable-icon icon_bug"></span>
      </button>
    </div>

    <!-- PII toggle -->
    {#if showPIIToggle && onTogglePII}
      <div class="button-wrapper">
        <button
          class="action-button pii-toggle-button"
          class:pii-toggle-active={piiRevealed}
          onclick={onTogglePII}
          aria-label={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
          title={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
        >
          <span class="clickable-icon {piiRevealed ? 'icon_visible' : 'icon_hidden'}"></span>
        </button>
      </div>
    {/if}
  </div>

  <!-- Right: minimize / close -->
  <div class="top-bar-right">
    <div class="button-wrapper">
      <button
        class="action-button"
        onclick={onClose}
        aria-label="Minimize"
        title="Minimize"
      >
        <span class="clickable-icon icon_minimize"></span>
      </button>
    </div>
  </div>
</div>

<style>
  /* Top bar sits in normal document flow — flex row, no absolute positioning.
     This ensures the content area (and gradient header banner) always starts
     below the buttons, keeping the header fully visible on all screen sizes. */
  .embed-top-bar {
    flex-shrink: 0;
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    /* Pointer-events disabled on the row itself; re-enabled per button group */
    pointer-events: none;
    /* z-index: keeps buttons above Leaflet map panes (z-index 400+) and any
       other high-z-index child rendered by embed fullscreens */
    position: relative;
    z-index: 1000;
  }

  .top-bar-left,
  .top-bar-right {
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: auto;
  }

  /* Pill wrapper — matches new-chat-button-wrapper in ActiveChat.svelte */
  .button-wrapper {
    background-color: var(--color-grey-10);
    border-radius: 40px;
    padding: 5.5px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .action-button {
    width: 30px;
    height: 30px;
    min-width: 30px;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    transition: background-color 0.2s;
  }

  .action-button:hover {
    background-color: rgba(0, 0, 0, 0.05);
  }

  .action-button .clickable-icon {
    width: 22px;
    height: 22px;
  }

  /* PII toggle: amber tint when sensitive data is revealed */
  .pii-toggle-button.pii-toggle-active {
    background-color: rgba(245, 158, 11, 0.3) !important;
  }

  .pii-toggle-button.pii-toggle-active:hover {
    background-color: rgba(245, 158, 11, 0.45) !important;
  }
</style>
