<!--
  frontend/packages/ui/src/components/embeds/FocusModeActivationEmbed.svelte
  
  Focus mode activation indicator embed.
  Renders a compact card showing:
  - App icon + focus mode name
  - Countdown timer (4,3,2,1) with animated progress bar during auto-activation
  - "Focus activated" state after countdown completes
  - Click-to-reject during countdown (adds system message and deactivates)
  
  This component is mounted by FocusModeActivationRenderer inside the chat message.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
  import { text } from '@repo/ui';

  /**
   * Props for the focus mode activation embed
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Full focus mode ID (e.g., 'web-research') */
    focusId: string;
    /** App ID that owns the focus mode */
    appId: string;
    /** Translated display name of the focus mode */
    focusModeName: string;
    /** Callback when the user rejects the focus mode during countdown */
    onReject?: (focusId: string, focusModeName: string) => void;
    /** Callback when the user deactivates the focus mode via context menu */
    onDeactivate?: (focusId: string) => void;
    /** Callback to open focus mode details in settings */
    onDetails?: (focusId: string, appId: string) => void;
  }

  let {
    id: _id,
    focusId,
    appId,
    focusModeName,
    onReject,
    onDeactivate: _onDeactivate,
    onDetails: _onDetails
  }: Props = $props();

  // These props are used by the renderer for context menu dispatch;
  // not directly referenced in this component's template.
  void _id;
  void _onDeactivate;
  void _onDetails;

  // Countdown duration in seconds
  const COUNTDOWN_SECONDS = 4;

  // State
  let countdownValue = $state(COUNTDOWN_SECONDS);
  let isActivated = $state(false);
  let isRejected = $state(false);
  let countdownInterval: ReturnType<typeof setInterval> | null = null;

  // Progress percentage for the progress bar (100% -> 0%)
  let progressPercent = $derived(
    isActivated ? 0 : (countdownValue / COUNTDOWN_SECONDS) * 100
  );

  // Status text shown on the card
  let statusText = $derived.by(() => {
    if (isRejected) {
      return '';
    }
    if (isActivated) {
      return $text('embeds.focus_mode.activated.text', { default: 'Focus activated' });
    }
    return $text('embeds.focus_mode.activating.text', {
      default: `Activate in ${countdownValue} sec ...`,
      values: { seconds: String(countdownValue) }
    });
  });

  /**
   * Start the countdown timer
   */
  function startCountdown() {
    countdownValue = COUNTDOWN_SECONDS;
    countdownInterval = setInterval(() => {
      countdownValue -= 1;
      if (countdownValue <= 0) {
        // Countdown complete - activate
        clearInterval(countdownInterval!);
        countdownInterval = null;
        isActivated = true;
      }
    }, 1000);
  }

  /**
   * Handle click during countdown to reject the focus mode
   */
  function handleRejectClick() {
    if (isActivated || isRejected) return;

    // Stop the countdown
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }

    isRejected = true;

    // Notify parent/renderer about the rejection
    onReject?.(focusId, focusModeName);
  }

  /**
   * Handle right-click / context menu on the embed
   * Dispatches a custom event that ChatMessage.svelte listens for
   */
  function handleContextMenu(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    // The context menu is handled by the embed renderer via data attributes
    // ChatMessage.svelte picks it up from the embed node
  }

  /**
   * Handle global ESC key to reject focus mode during countdown
   */
  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && !isActivated && !isRejected) {
      event.preventDefault();
      handleRejectClick();
    }
  }

  onMount(() => {
    startCountdown();

    // Listen for ESC key globally (not just when element is focused)
    document.addEventListener('keydown', handleKeydown);

    return () => {
      document.removeEventListener('keydown', handleKeydown);
      if (countdownInterval) {
        clearInterval(countdownInterval);
      }
    };
  });
</script>

{#if !isRejected}
  <div
    class="focus-mode-activation"
    class:activated={isActivated}
    class:counting={!isActivated}
    data-focus-id={focusId}
    data-app-id={appId}
    data-embed-type="focus-mode-activation"
    role="button"
    tabindex="0"
    oncontextmenu={handleContextMenu}
    onclick={!isActivated ? handleRejectClick : undefined}
    onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!isActivated) handleRejectClick(); } }}
  >
    <!-- App icon and focus mode info -->
    <div class="focus-header">
      <div class="app-icon-container" style="--app-color: var(--color-app-{appId}, var(--color-primary-50))">
        <div class="app-icon icon_app_{appId}"></div>
      </div>
      <div class="focus-info">
        <span class="focus-name">{focusModeName}</span>
        <span class="focus-status" class:active-status={isActivated}>{statusText}</span>
      </div>
    </div>

    <!-- Progress bar (only during countdown) -->
    {#if !isActivated}
      <div class="progress-bar-container">
        <div
          class="progress-bar"
          style="width: {progressPercent}%"
        ></div>
      </div>
    {/if}
  </div>

  <!-- Helper text below the card during countdown -->
  {#if !isActivated}
    <div class="reject-hint">
      {$text('embeds.focus_mode.reject_hint.text', {
        default: 'Click or press ESC to prevent focus mode &\ncontinue regular chat'
      })}
    </div>
  {/if}
{/if}

<style>
  .focus-mode-activation {
    display: inline-flex;
    flex-direction: column;
    background: var(--color-grey-10, #f7f7f7);
    border-radius: 12px;
    padding: 10px 14px;
    gap: 8px;
    cursor: default;
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
    max-width: 280px;
    user-select: none;
    -webkit-user-select: none;
    position: relative;
    overflow: hidden;
  }

  .focus-mode-activation.counting {
    cursor: pointer;
  }

  .focus-mode-activation.counting:hover {
    background: var(--color-grey-15, #efefef);
  }

  .focus-mode-activation.activated {
    background: var(--color-success-5, #f0faf4);
    border: 1px solid var(--color-success-20, #c0e8cf);
  }

  .focus-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .app-icon-container {
    width: 32px;
    height: 32px;
    min-width: 32px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--app-color, var(--color-primary-50));
  }

  .app-icon {
    width: 18px;
    height: 18px;
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    filter: brightness(0) invert(1);
  }

  .focus-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .focus-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-grey-80, #333);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .focus-status {
    font-size: 11px;
    color: var(--color-grey-50, #888);
    line-height: 1.2;
  }

  .focus-status.active-status {
    color: var(--color-success-60, #34a853);
    font-weight: 500;
  }

  /* Progress bar */
  .progress-bar-container {
    width: 100%;
    height: 3px;
    background: var(--color-grey-15, #efefef);
    border-radius: 2px;
    overflow: hidden;
  }

  .progress-bar {
    height: 100%;
    background: var(--color-success-50, #4caf50);
    border-radius: 2px;
    transition: width 1s linear;
  }

  /* Reject hint text */
  .reject-hint {
    font-size: 11px;
    color: var(--color-grey-40, #aaa);
    margin-top: 4px;
    padding-left: 2px;
    line-height: 1.3;
    white-space: pre-line;
  }

  /* Dark mode */
  :global(.dark) .focus-mode-activation {
    background: var(--color-grey-90, #1a1a1a);
  }

  :global(.dark) .focus-mode-activation.counting:hover {
    background: var(--color-grey-85, #252525);
  }

  :global(.dark) .focus-mode-activation.activated {
    background: var(--color-success-95, #0a2a14);
    border-color: var(--color-success-80, #1a6030);
  }

  :global(.dark) .focus-name {
    color: var(--color-grey-20, #eaeaea);
  }

  :global(.dark) .focus-status {
    color: var(--color-grey-50, #888);
  }

  :global(.dark) .focus-status.active-status {
    color: var(--color-success-40, #7ad09a);
  }

  :global(.dark) .progress-bar-container {
    background: var(--color-grey-85, #252525);
  }

  :global(.dark) .reject-hint {
    color: var(--color-grey-60, #666);
  }
</style>
