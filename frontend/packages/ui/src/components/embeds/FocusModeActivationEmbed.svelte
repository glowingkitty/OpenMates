<!--
  frontend/packages/ui/src/components/embeds/FocusModeActivationEmbed.svelte
  
  Focus mode activation indicator embed.
  Renders a compact bar (styled like BasicInfosBar) showing:
  - App icon in gradient circle (uses the app's gradient color)
  - Focus/insight skill icon (in focus-mode purple)
  - Focus mode name + status text
  - Countdown timer with progress bar during auto-activation (first time only)
  - "Focus activated" state after countdown completes
  - Click-to-reject during countdown (adds system message and deactivates)
  
  CRITICAL: The countdown should only run ONCE per embed ID. When the component
  is remounted (scroll, tab switch, etc.), it should show the activated state
  immediately if the countdown already completed for this embed.
  
  This component is mounted by FocusModeActivationRenderer inside the chat message.
-->

<script lang="ts" module>
  /**
   * Module-level set tracking which embed IDs have already completed activation.
   * This persists across component remounts (scroll in/out, tab switches) to ensure
   * the countdown animation only plays once per embed, ever.
   */
  const activatedEmbedIds = new Set<string>();
  
  /**
   * Module-level set tracking which embed IDs have been rejected.
   * Rejected embeds should remain hidden on remount.
   */
  const rejectedEmbedIds = new Set<string>();
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';

  /**
   * Props for the focus mode activation embed
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Full focus mode ID (e.g., 'jobs-career_insights') */
    focusId: string;
    /** App ID that owns the focus mode */
    appId: string;
    /** Translated display name of the focus mode (translation key like 'jobs.career_insights') */
    focusModeName: string;
    /**
     * Whether this focus mode is already active on the chat (from server/IndexedDB state).
     * When true, the countdown is skipped entirely and the component shows the static
     * "Focus activated" state immediately. This prevents the countdown from replaying
     * every time the user revisits a chat where a focus mode was previously activated.
     */
    alreadyActive?: boolean;
    /** Callback when the user rejects the focus mode during countdown */
    onReject?: (focusId: string, focusModeName: string) => void;
    /** Callback when the user deactivates the focus mode via context menu */
    onDeactivate?: (focusId: string) => void;
    /** Callback to open focus mode details in settings */
    onDetails?: (focusId: string, appId: string) => void;
    /**
     * Callback when the user right-clicks or long-presses the embed.
     * Opens the FocusModeContextMenu with Cancel/Stop/Details options.
     */
    onContextMenu?: (event: MouseEvent | TouchEvent, state: { isActivated: boolean; isRejected: boolean }) => void;
  }

  let {
    id,
    focusId,
    appId,
    focusModeName,
    alreadyActive = false,
    onReject,
    onDeactivate: _onDeactivate,
    onDetails: _onDetails,
    onContextMenu: _onContextMenu,
  }: Props = $props();

  // These props are used by the renderer for context menu dispatch;
  // not directly referenced in this component's template.
  void _onDeactivate;
  void _onDetails;

  // Countdown duration in seconds
  const COUNTDOWN_SECONDS = 4;

  // Check if this embed was already activated or rejected in a previous mount.
  // alreadyActive=true means the server/IndexedDB state confirms this focus mode
  // is active on the chat, so we skip the countdown entirely (e.g., when revisiting a chat).
  const wasAlreadyActivated = alreadyActive || activatedEmbedIds.has(id);
  const wasAlreadyRejected = !alreadyActive && rejectedEmbedIds.has(id);

  // State
  let countdownValue = $state(wasAlreadyActivated ? 0 : COUNTDOWN_SECONDS);
  let isActivated = $state(wasAlreadyActivated);
  let isRejected = $state(wasAlreadyRejected);
  let countdownInterval: ReturnType<typeof setInterval> | null = null;

  // Resolve the focus mode name — may be a translation key like "jobs.career_insights"
  // or a pre-resolved display name from the backend like "Career Insights"
  let focusFallbackName = $derived(
    focusModeName.split('.').slice(-2, -1)[0]?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || focusModeName
  );
  let displayName = $derived.by(() => {
    const translated = $text(focusModeName);
    // If $text returned the raw key (translation not found and default wasn't applied),
    // fall back to the human-readable name
    if (translated === focusModeName && focusFallbackName !== focusModeName) return focusFallbackName;
    return translated || focusFallbackName;
  });

  // Status text shown on the card
  let statusText = $derived.by(() => {
    if (isRejected) {
      return '';
    }
    if (isActivated) {
      return $text('embeds.focus_mode.activated');
    }
    return $text('embeds.focus_mode.activating', {
      values: { seconds: String(countdownValue) }
    });
  });

  // Progress percentage for the progress bar (100% -> 0%)
  let progressPercent = $derived(
    isActivated ? 0 : (countdownValue / COUNTDOWN_SECONDS) * 100
  );

  // App gradient style for the icon circle
  let appGradientStyle = $derived(`background: var(--color-app-${appId});`);

  /**
   * Start the countdown timer (only if not already activated)
   */
  function startCountdown() {
    if (wasAlreadyActivated) return;
    
    countdownValue = COUNTDOWN_SECONDS;
    countdownInterval = setInterval(() => {
      countdownValue -= 1;
      if (countdownValue <= 0) {
        // Countdown complete - activate
        clearInterval(countdownInterval!);
        countdownInterval = null;
        isActivated = true;
        activatedEmbedIds.add(id);
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
    rejectedEmbedIds.add(id);

    // Notify parent/renderer about the rejection
    onReject?.(focusId, focusModeName);
  }

  /**
   * Handle right-click / context menu on the embed.
   * Opens the FocusModeContextMenu via the onContextMenu callback.
   */
  function handleContextMenu(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    _onContextMenu?.(event, { isActivated, isRejected });
  }

  // --- Long-press (touch) handling for mobile context menu ---
  const LONG_PRESS_DURATION = 500;
  const TOUCH_MOVE_THRESHOLD = 10;
  let touchTimer: ReturnType<typeof setTimeout> | null = null;
  let touchStartX = 0;
  let touchStartY = 0;

  function handleTouchStart(event: TouchEvent) {
    if (event.touches.length !== 1) {
      clearTouchTimer();
      return;
    }
    const touch = event.touches[0];
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;

    touchTimer = setTimeout(() => {
      touchTimer = null;
      // Prevent the subsequent touchend from triggering a click/reject
      event.preventDefault();
      // Haptic feedback
      if (navigator.vibrate) {
        navigator.vibrate(50);
      }
      _onContextMenu?.(event, { isActivated, isRejected });
    }, LONG_PRESS_DURATION);
  }

  function handleTouchMove(event: TouchEvent) {
    if (!touchTimer) return;
    const touch = event.touches[0];
    const deltaX = Math.abs(touch.clientX - touchStartX);
    const deltaY = Math.abs(touch.clientY - touchStartY);
    if (deltaX > TOUCH_MOVE_THRESHOLD || deltaY > TOUCH_MOVE_THRESHOLD) {
      clearTouchTimer();
    }
  }

  function handleTouchEnd() {
    clearTouchTimer();
  }

  function clearTouchTimer() {
    if (touchTimer) {
      clearTimeout(touchTimer);
      touchTimer = null;
    }
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
    // Only start countdown if not already activated/rejected
    if (!wasAlreadyActivated && !wasAlreadyRejected) {
      startCountdown();
    }

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
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    class="focus-mode-bar"
    class:activated={isActivated}
    class:counting={!isActivated}
    data-focus-id={focusId}
    data-app-id={appId}
    data-embed-type="focus-mode-activation"
    role={!isActivated ? 'button' : 'presentation'}
    tabindex={!isActivated ? 0 : -1}
    oncontextmenu={handleContextMenu}
    ontouchstart={handleTouchStart}
    ontouchmove={handleTouchMove}
    ontouchend={handleTouchEnd}
    onclick={!isActivated ? handleRejectClick : undefined}
    onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!isActivated) handleRejectClick(); } }}
  >
    <!-- App icon in gradient circle (matches BasicInfosBar style) -->
    <div class="app-icon-circle {appId}" style={appGradientStyle}>
      <div class="icon_rounded {appId}"></div>
    </div>
    
    <!-- Focus/insight skill icon (purple color for focus mode) -->
    <div class="focus-skill-icon"></div>
    
    <!-- Status text -->
    <div class="status-text">
      <span class="status-label">{displayName}</span>
      <span class="status-value" class:active-status={isActivated}>{statusText}</span>
    </div>

    <!-- Progress bar (only during countdown, overlaid at bottom) -->
    {#if !isActivated}
      <div class="progress-bar-container">
        <div
          class="progress-bar"
          style="width: {progressPercent}%"
        ></div>
      </div>
    {/if}
  </div>

  <!-- Helper text below the bar during countdown -->
  {#if !isActivated}
    <div class="reject-hint">
      {$text('embeds.focus_mode.reject_hint', {
        default: 'Click or press ESC to prevent focus mode &\ncontinue regular chat'
      })}
    </div>
  {/if}
{/if}

<style>
  /* ===========================================
     Focus Mode Bar - Styled like BasicInfosBar
     =========================================== */
  
  .focus-mode-bar {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-30);
    border-radius: 30px;
    padding: 0;
    user-select: none;
    -webkit-user-select: none;
    position: relative;
    overflow: hidden;
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
    max-width: 380px;
  }

  .focus-mode-bar.counting {
    cursor: pointer;
  }

  .focus-mode-bar.counting:hover {
    background-color: var(--color-grey-25);
  }

  /* App icon circle: 61x61px with gradient background (same as BasicInfosBar) */
  .focus-mode-bar .app-icon-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  /* Override the default icon_rounded positioning for flex layout */
  .focus-mode-bar .app-icon-circle .icon_rounded {
    width: 26px;
    height: 26px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }

  /* Make the icon white on gradient background */
  .focus-mode-bar .app-icon-circle .icon_rounded {
    background: transparent !important;
  }

  .focus-mode-bar .app-icon-circle .icon_rounded::after {
    filter: brightness(0) invert(1);
  }

  /* Focus/insight skill icon: uses the focus mode purple gradient color */
  .focus-mode-bar .focus-skill-icon {
    width: 29px;
    height: 29px;
    min-width: 29px;
    /* Use focus mode purple instead of grey */
    background-color: var(--icon-focus-background-start, #5951D0);
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
    flex-shrink: 0;
  }

  /* Status text container */
  .focus-mode-bar .status-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
    flex: 1;
    min-width: 0;
    gap: 2px;
    padding-right: 16px;
  }

  .focus-mode-bar .status-label {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .focus-mode-bar .status-value {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
  }

  .focus-mode-bar .status-value.active-status {
    color: var(--color-success-60, #34a853);
    font-weight: 500;
  }

  /* Progress bar - thin bar at the very bottom of the bar */
  .focus-mode-bar .progress-bar-container {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    width: 100%;
    height: 3px;
    background: var(--color-grey-25);
    overflow: hidden;
  }

  .focus-mode-bar .progress-bar {
    height: 100%;
    background: var(--color-success-50, #4caf50);
    border-radius: 0 2px 2px 0;
    transition: width 1s linear;
  }

  /* Reject hint text below the bar */
  .reject-hint {
    font-size: 11px;
    color: var(--color-grey-40, #aaa);
    margin-top: 4px;
    padding-left: 2px;
    line-height: 1.3;
    white-space: pre-line;
  }

  /* Dark mode adjustments */
  :global(.dark) .focus-mode-bar .status-value.active-status {
    color: var(--color-success-40, #7ad09a);
  }

  :global(.dark) .reject-hint {
    color: var(--color-grey-60, #666);
  }
</style>
