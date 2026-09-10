<!--
  frontend/packages/ui/src/components/embeds/EmbedTopBar.svelte

  Action button row rendered at the top of every embed fullscreen view.
  Overlays the scrollable header and content. Shared overlap detection switches
  controls to translucent backgrounds and white icons while over the banner.

  Layout:
  - Left side: Report issue, responsive Share, and More with secondary actions
  - Right side: Close button

  All buttons use the same pill-wrapper + circular-icon design as the new-chat
  button in ActiveChat.svelte.
-->

<script lang="ts">
  import HeaderActionMenu from '../HeaderActionMenu.svelte';
  import { text } from '@repo/ui';
  import { headerOverlayControls } from '../../actions/headerOverlayControls';

  interface Props {
    /** Whether to show the "restore chat" button (ultra-wide side-by-side mode). */
    showChatButton?: boolean;
    /** Whether to show the share button (default true). */
    showShare?: boolean;
    /** Whether to show the copy button (truthy = show). */
    showCopy?: boolean;
    /** Whether to show the download button (truthy = show). */
    showDownload?: boolean;
    /** Optional prepared download URL. When set, the download action renders as a native anchor. */
    downloadHref?: string | null;
    /** Suggested filename for native anchor downloads. */
    downloadFilename?: string;
    /** Whether to show the add-to-calendar button (truthy = show). */
    showCalendar?: boolean;
    /** Whether to show the preview/render button (for markdown/HTML code embeds). */
    showPreview?: boolean;
    /** Whether to show the code run button. */
    showRun?: boolean;
    /** Whether a code run is currently active (highlights the button). */
    runActive?: boolean;
    /** Whether preview mode is currently active (highlights the button). */
    previewActive?: boolean;
    /** Whether to show the PII hide/show toggle. */
    showPIIToggle?: boolean;
    /** Whether PII is currently revealed (controls toggle visual state). */
    piiRevealed?: boolean;
    /** Whether to show the pre-send action that keeps original PII in this embed. */
    showPIIIncludeOriginal?: boolean;

    onClose: () => void;
    closeTestId?: string;
    onShare?: () => void;
    onCopy?: () => void;
    onDownload?: () => void;
    onCalendar?: () => void;
    onRun?: () => void;
    onTogglePreview?: () => void;
    onReportIssue?: () => void;
    /** Whether to show the admin debug toggle button. */
    showDebug?: boolean;
    /** Whether debug mode is currently active (highlights the button). */
    debugActive?: boolean;
    onToggleDebug?: () => void;
    onShowChat?: () => void;
    onTogglePII?: () => void;
    onIncludeOriginalPII?: () => void;
  }

  let {
    showChatButton = false,
    showShare = true,
    showCopy = false,
    showDownload = false,
    downloadHref = null,
    downloadFilename = 'download',
    showCalendar = false,
    showPreview = false,
    showRun = false,
    runActive = false,
    previewActive = false,
    showPIIToggle = false,
    piiRevealed = false,
    showPIIIncludeOriginal = false,
    onClose,
    closeTestId = 'embed-minimize',
    onShare,
    onCopy,
    onDownload,
    onCalendar,
    onRun,
    onTogglePreview,
    onReportIssue,
    showDebug = false,
    debugActive = false,
    onToggleDebug,
    onShowChat,
    onTogglePII,
    onIncludeOriginalPII,
  }: Props = $props();
</script>

<div class="embed-top-bar" use:headerOverlayControls>
  <HeaderActionMenu>
    {#snippet report()}
      <!-- Report Issue (always shown) -->
      <div class="button-wrapper">
        <button
          data-testid="embed-report-issue-button"
          class="header-action"
          onclick={onReportIssue}
          aria-label={$text('header.report_issue')}
          title={$text('header.report_issue')}
          ><span class="clickable-icon icon_bug top-button" aria-hidden="true"
          ></span><span class="action-label"
            >{$text('header.report_issue')}</span
          ></button
        >
      </div>
    {/snippet}
    {#snippet share()}
      <!-- Share -->
      {#if showShare}
        <div class="button-wrapper">
          <button
            class="header-action"
            data-testid="embed-share-button"
            onclick={onShare}
            aria-label={$text('chat.share')}
            title={$text('chat.share')}
            ><span
              class="clickable-icon icon_share top-button"
              aria-hidden="true"
            ></span><span class="action-label">{$text('chat.share')}</span
            ></button
          >
        </div>
      {/if}
    {/snippet}
    {#snippet actions()}
      <!-- Restore chat (ultra-wide side-by-side mode) -->
      {#if showChatButton && onShowChat}
        <div class="button-wrapper">
          <button
            class="header-action"
            onclick={onShowChat}
            aria-label={$text('chat.show_chat')}
            title={$text('chat.show_chat')}
            ><span
              class="clickable-icon icon_chat top-button"
              aria-hidden="true"
            ></span><span class="action-label">{$text('chat.show_chat')}</span
            ></button
          >
        </div>
      {/if}

      <!-- Copy -->
      {#if showCopy && onCopy}
        <div class="button-wrapper">
          <button
            class="header-action"
            onclick={onCopy}
            aria-label={$text('common.copy')}
            title={$text('common.copy')}
            ><span
              class="clickable-icon icon_copy top-button"
              aria-hidden="true"
            ></span><span class="action-label">{$text('common.copy')}</span></button
          >
        </div>
      {/if}

      <!-- Download -->
      {#if showDownload && onDownload}
        <div class="button-wrapper">
          {#if downloadHref}
            <a
              class="header-action"
              data-testid="embed-download-button"
              href={downloadHref}
              download={downloadFilename}
              aria-label={$text('common.download')}
              title={$text('common.download')}
              ><span
                class="clickable-icon icon_download top-button"
                aria-hidden="true"
              ></span><span class="action-label">{$text('common.download')}</span></a
            >
          {:else}
            <button
              class="header-action"
              data-testid="embed-download-button"
              onclick={onDownload}
              aria-label={$text('common.download')}
              title={$text('common.download')}
              ><span
                class="clickable-icon icon_download top-button"
                aria-hidden="true"
              ></span><span class="action-label">{$text('common.download')}</span></button
            >
          {/if}
        </div>
      {/if}

      <!-- Add to calendar -->
      {#if showCalendar && onCalendar}
        <div class="button-wrapper">
          <button
            class="header-action"
            data-testid="embed-calendar-button"
            onclick={onCalendar}
            aria-label="Add to calendar"
            title="Add to calendar"
            ><span
              class="clickable-icon icon_calendar top-button"
              aria-hidden="true"
            ></span><span class="action-label">Add to calendar</span></button
          >
        </div>
      {/if}

      <!-- Run code in sandbox -->
      {#if showRun && onRun}
        <div class="button-wrapper" class:run-active={runActive}>
          <button
            class="header-action"
            data-testid="embed-run-button"
            onclick={onRun}
            aria-label={$text('app_skills.code.run')}
            title={$text('app_skills.code.run')}
            ><span
              class="clickable-icon icon_play top-button"
              aria-hidden="true"
            ></span><span class="action-label"
              >{$text('app_skills.code.run')}</span
            ></button
          >
        </div>
      {/if}

      <!-- Preview / Render (for markdown/HTML code embeds) -->
      {#if showPreview && onTogglePreview}
        <div class="button-wrapper" class:preview-active={previewActive}>
          <button
            class="header-action"
            data-testid="embed-preview-button"
            onclick={onTogglePreview}
            aria-label={previewActive ? 'Hide preview' : 'Show preview'}
            title={previewActive ? 'Hide preview' : 'Show preview'}
            ><span
              class="clickable-icon icon_preview top-button"
              aria-hidden="true"
            ></span><span class="action-label"
              >{previewActive ? 'Hide preview' : 'Show preview'}</span
            ></button
          >
        </div>
      {/if}

      <!-- Debug toggle (admin-only, controlled by parent) -->
      {#if showDebug && onToggleDebug}
        <div class="button-wrapper">
          <button
            data-testid="embed-toggle-debug"
            class="header-action"
            class:debug-mode-active={debugActive}
            onclick={onToggleDebug}
            aria-label={debugActive ? 'End debugging' : 'Start debugging'}
            title={debugActive ? 'End debugging' : 'Start debugging'}
            ><span
              class="clickable-icon icon_task top-button"
              aria-hidden="true"
            ></span><span class="action-label"
              >{debugActive ? 'End debugging' : 'Start debugging'}</span
            ></button
          >
        </div>
      {/if}

      <!-- PII toggle -->
      {#if showPIIToggle && onTogglePII}
        <div class="button-wrapper">
          <button
            data-testid="embed-pii-toggle"
            data-pii-revealed={piiRevealed ? 'true' : 'false'}
            class="header-action"
            class:pii-toggle-active={piiRevealed}
            onclick={onTogglePII}
            aria-label={piiRevealed
              ? $text('embeds.pii_hide')
              : $text('embeds.pii_show')}
            title={piiRevealed
              ? $text('embeds.pii_hide')
              : $text('embeds.pii_show')}
            ><span
              class="clickable-icon {piiRevealed
                ? 'icon_visible'
                : 'icon_hidden'} top-button"
              aria-hidden="true"
            ></span><span class="action-label"
              >{piiRevealed
                ? $text('embeds.pii_hide')
                : $text('embeds.pii_show')}</span
            ></button
          >
        </div>
      {/if}

      {#if showPIIIncludeOriginal && onIncludeOriginalPII}
        <div class="button-wrapper pii-include-original">
          <button
            data-testid="embed-pii-include-original"
            class="header-action"
            onclick={onIncludeOriginalPII}
            aria-label={$text('embeds.pii_include_original')}
            title={$text('embeds.pii_include_original')}
            ><span
              class="clickable-icon icon_lock top-button"
              aria-hidden="true"
            ></span><span class="action-label"
              >{$text('embeds.pii_include_original')}</span
            ></button
          >
        </div>
      {/if}{/snippet}
    {#snippet close()}
      <div class="button-wrapper">
        <button
          class="header-action"
          data-testid={closeTestId}
          onclick={onClose}
          aria-label={$text('common.close')}
          title={$text('common.close')}
          ><span class="clickable-icon icon_close top-button" aria-hidden="true"
          ></span><span class="action-label">{$text('common.close')}</span
          ></button
        >
      </div>{/snippet}
  </HeaderActionMenu>
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
    padding: var(--spacing-6) var(--spacing-8);
    display: flex;
    justify-content: space-between;
    align-items: center;
    /* Pointer-events disabled on the row itself; re-enabled per button group */
    pointer-events: none;
    /* Sits above EmbedHeader (z-index 2) and Leaflet panes (z-index 400+) */
    z-index: var(--z-index-modal);
  }

  .debug-mode-active {
    color: var(--color-primary) !important;
  }

  .run-active {
    color: var(--color-primary) !important;
  }

  /* Pill wrapper — matches .new-chat-button-wrapper in ActiveChat.svelte */
  .button-wrapper {
    position: relative;
    z-index: 1;
    background-color: var(--color-grey-10);
    border-radius: 40px;
    padding: var(--spacing-4);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      background-color var(--duration-normal) var(--easing-in-out),
      transform var(--duration-fast) var(--easing-in-out),
      box-shadow var(--duration-fast) var(--easing-in-out);
    cursor: pointer;
    pointer-events: auto;
  }

  .top-button {
    pointer-events: auto;
  }

  .button-wrapper:hover {
    transform: scale(1.08);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }

  .button-wrapper:active {
    transform: scale(0.95);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  }

  :global(a.clickable-icon.top-button) {
    display: block;
    width: 25px;
    height: 25px;
    cursor: pointer;
    background: var(--color-primary);
    -webkit-mask-position: center;
    -webkit-mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-position: center;
    mask-repeat: no-repeat;
    mask-size: contain;
  }

  /* Preview toggle: primary tint when preview mode is active */
  .preview-active {
    background-color: rgba(99, 102, 241, 0.25) !important;
  }

  /* PII toggle: amber tint when sensitive data is revealed — matches ActiveChat.svelte */
  .pii-toggle-active {
    background-color: rgba(245, 158, 11, 0.3) !important;
  }

  :global(.clickable-icon.icon_calendar) {
    -webkit-mask-image: url('@openmates/ui/static/icons/calendar.svg');
    mask-image: url('@openmates/ui/static/icons/calendar.svg');
  }
</style>
