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
    /** Whether to show the admin debug toggle button. */
    showDebug?: boolean;
    /** Whether debug mode is currently active (highlights the button). */
    debugActive?: boolean;
    onToggleDebug?: () => void;
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
    showDebug = false,
    debugActive = false,
    onToggleDebug,
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
          class="clickable-icon icon_chat top-button"
          onclick={onShowChat}
          aria-label={$text('chat.show_chat')}
          title={$text('chat.show_chat')}
        ></button>
      </div>
    {/if}

    <!-- Share -->
    {#if showShare}
      <div class="button-wrapper">
        <button
          class="clickable-icon icon_share top-button"
          onclick={onShare}
          aria-label={$text('chat.share')}
          title={$text('chat.share')}
        ></button>
      </div>
    {/if}

    <!-- Copy -->
    {#if showCopy && onCopy}
      <div class="button-wrapper">
        <button
          class="clickable-icon icon_copy top-button"
          onclick={onCopy}
          aria-label="Copy"
          title="Copy"
        ></button>
      </div>
    {/if}

    <!-- Download -->
    {#if showDownload && onDownload}
      <div class="button-wrapper">
        <button
          class="clickable-icon icon_download top-button"
          onclick={onDownload}
          aria-label="Download"
          title="Download"
        ></button>
      </div>
    {/if}

    <!-- Report Issue (always shown) -->
    <div class="button-wrapper">
      <button
        class="clickable-icon icon_bug top-button"
        onclick={onReportIssue}
        aria-label={$text('header.report_issue')}
        title={$text('header.report_issue')}
      ></button>
    </div>

    <!-- Debug toggle (admin-only, controlled by parent) -->
    {#if showDebug && onToggleDebug}
      <div class="button-wrapper">
        <button
          class="clickable-icon icon_task top-button"
          class:debug-mode-active={debugActive}
          onclick={onToggleDebug}
          aria-label={debugActive ? 'End debugging' : 'Start debugging'}
          title={debugActive ? 'End debugging' : 'Start debugging'}
        ></button>
      </div>
    {/if}

    <!-- PII toggle -->
    {#if showPIIToggle && onTogglePII}
      <div class="button-wrapper">
        <button
          class="clickable-icon {piiRevealed ? 'icon_visible' : 'icon_hidden'} top-button"
          class:pii-toggle-active={piiRevealed}
          onclick={onTogglePII}
          aria-label={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
          title={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
        ></button>
      </div>
    {/if}
  </div>

  <!-- Right: minimize / close -->
  <div class="top-bar-right">
    <div class="button-wrapper">
      <button
        class="clickable-icon icon_minimize top-button"
        onclick={onClose}
        aria-label="Minimize"
        title="Minimize"
      ></button>
    </div>
  </div>
</div>

<style>
  /* Top bar overlays the gradient header — position absolute so the header
     remains fully visible beneath it. No background on the row itself.
     Buttons use the same pill-wrapper + circular-icon design as the
     new-chat button and action buttons in ActiveChat.svelte. */
  .embed-top-bar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    /* Pointer-events disabled on the row itself; re-enabled per button group */
    pointer-events: none;
    /* Sits above EmbedHeader (z-index 2) and Leaflet panes (z-index 400+) */
    z-index: 1000;
  }

  .debug-mode-active {
    color: var(--color-primary) !important;
  }

  .top-bar-left,
  .top-bar-right {
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: auto;
  }

  /* Pill wrapper — matches .new-chat-button-wrapper in ActiveChat.svelte */
  .button-wrapper {
    background-color: var(--color-grey-10);
    border-radius: 40px;
    padding: 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
    cursor: pointer;
  }

  .button-wrapper:hover {
    transform: scale(1.08);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }

  .button-wrapper:active {
    transform: scale(0.95);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  }

  /* PII toggle: amber tint when sensitive data is revealed — matches ActiveChat.svelte */
  .pii-toggle-active {
    background-color: rgba(245, 158, 11, 0.3) !important;
  }
</style>
