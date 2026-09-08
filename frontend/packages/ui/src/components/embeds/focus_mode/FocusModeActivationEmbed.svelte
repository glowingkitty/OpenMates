<!--
  frontend/packages/ui/src/components/embeds/focus_mode/FocusModeActivationEmbed.svelte
  
  Focus mode activation indicator embed.
  Renders a compact bar (styled like BasicInfosBar) showing:
  - App icon in gradient circle (uses the app's gradient color)
  - Focus/insight skill icon (in focus-mode purple)
  - Focus mode name + status text
  - Countdown timer with progress bar during auto-activation (first time only)
  - "Focus activated" state after countdown completes
  - Click-to-reject during countdown (adds system message and deactivates)
  - Click/tap/Enter/Space on activated embed opens the context menu (stop/details)
  
  Countdown eligibility comes only from a live server event bound to this chat/embed.
  Historical rendering and timer expiry never mutate active focus metadata.
  The server activation event remains authoritative.

  This component is mounted by FocusModeActivationRenderer inside the chat message.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { pendingFocusActivationStore } from '../../../stores/pendingFocusActivationStore';
  import { activeChatFocusStore } from '../../../stores/activeChatFocusStore';

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
    /** Originating chat, never inferred again by timer callbacks. */
    chatId?: string;
    /** Preview-only explicit live deadline; production uses transient server events. */
    pendingUntil?: number;
    /** Callback when the user rejects the focus mode during countdown */
    onReject?: (focusId: string, focusModeName: string) => void;
    /** Callback when the countdown completes and the focus mode becomes active */
    onActivate?: (focusId: string) => void;
    /** Callback when the user deactivates the focus mode via context menu */
    onDeactivate?: (focusId: string) => void;
    /** Callback to open focus mode details in settings */
    onDetails?: (focusId: string, appId: string) => void;
    /**
     * Callback when the user clicks, right-clicks, or long-presses the embed.
     * Opens the FocusModeContextMenu with Cancel/Stop/Details options.
     * Regular click/tap/keyboard triggers this after activation; right-click always works.
     */
    onContextMenu?: (event: MouseEvent | TouchEvent, state: { isActivated: boolean; isRejected: boolean }) => void;
  }

  let {
    id,
    focusId,
    appId,
    focusModeName,
    alreadyActive = false,
    chatId = "",
    pendingUntil = 0,
    onReject,
    onActivate: _onActivate,
    onDeactivate: _onDeactivate,
    onDetails: _onDetails,
    onContextMenu: _onContextMenu,
  }: Props = $props();

  // These props are used by the renderer for context menu dispatch;
  // not directly referenced in this component's template.
  $effect(() => { void _onDeactivate; void _onDetails; void _onActivate; });

  // Countdown duration in seconds
  const COUNTDOWN_SECONDS = 4;

  // State
  let countdownValue = $state(COUNTDOWN_SECONDS);
  let isActivated = $derived(alreadyActive || (!!chatId && $activeChatFocusStore[chatId] === focusId));
  let now = $state(Date.now());
  let deadline = $derived(pendingUntil || ($pendingFocusActivationStore[id]?.chatId === chatId && $pendingFocusActivationStore[id]?.focusId === focusId ? $pendingFocusActivationStore[id].expiresAt : 0));
  let isPending = $derived(!isActivated && !isRejected && deadline > now);
  let isRejected = $state(false);
  let countdownInterval: ReturnType<typeof setInterval> | null = null;

  // Resolve the focus mode name — may be a translation key like "focus_modes.jobs_career_insights"
  // or a pre-resolved display name from the backend like "Career Insights"
  // Build a human-readable fallback from the focus ID: "jobs-career_insights" → "Career Insights"
  let focusFallbackName = $derived(
    focusId
      ? focusId.split('-').slice(1).join(' ').replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
      : focusModeName
  );
  let displayName = $derived.by(() => {
    // First try looking up focusModeName as a translation key
    const translated = $text(focusModeName);
    // $text returns "[T:key]" when the key is not found
    if (!translated.startsWith('[T:')) return translated;

    // If the backend sent a pre-resolved display name (not a translation key),
    // use it directly — it won't be a valid key so $text returns a placeholder
    if (!focusModeName.includes('.')) return focusModeName;

    // Last resort: human-readable fallback derived from the focus ID
    return focusFallbackName;
  });

  // Status text shown on the card
  let statusText = $derived.by(() => {
    if (isRejected) {
      return '';
    }
    if (!isPending) {
      return isActivated ? $text('embeds.focus_mode.activated') : '';
    }
    return $text('embeds.focus_mode.activating', {
      values: { seconds: String(countdownValue) }
    });
  });

  // Progress percentage for the progress bar (100% -> 0%)
  let progressPercent = $derived(
    isPending ? Math.min(100, (countdownValue / COUNTDOWN_SECONDS) * 100) : 0
  );

  // App gradient style for the icon circle
  let appGradientStyle = $derived(`background: var(--color-app-${appId});`);

  /**
   * Handle click during countdown to reject the focus mode
   */
  function handleRejectClick() {
    if (!isPending) return;

    // Stop the countdown
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }

    isRejected = true;
    pendingFocusActivationStore.clear(id);

    // Notify parent/renderer about the rejection
    onReject?.(focusId, focusModeName);
  }

  /**
   * Handle regular click on the embed.
   * - During countdown: rejects the focus mode (cancels activation).
   * - After activation: opens the context menu (same as right-click).
   */
  function handleClick(event: MouseEvent) {
    if (isPending) {
      handleRejectClick();
    } else {
      if (!isActivated) { _onDetails?.(focusId, appId); return; }
      // Active state exposes controls; historical state only opens details.
      event.preventDefault();
      event.stopPropagation();
      _onContextMenu?.(event, { isActivated, isRejected });
    }
  }

  /**
   * Handle keyboard interaction (Enter/Space).
   * - During countdown: rejects the focus mode.
   * - After activation: opens the context menu.
   */
  function handleKeyPress(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (isPending) {
        handleRejectClick();
      } else {
        if (!isActivated) { _onDetails?.(focusId, appId); return; }
        // Create a synthetic position based on the element for the context menu
        const target = e.currentTarget as HTMLElement;
        const rect = target.getBoundingClientRect();
        const syntheticEvent = new MouseEvent('click', {
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2,
          bubbles: true,
        });
        _onContextMenu?.(syntheticEvent, { isActivated, isRejected });
      }
    }
  }

  /**
   * Handle right-click / context menu on the embed.
   * Opens the FocusModeContextMenu via the onContextMenu callback.
   */
  function handleContextMenu(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    if (!isPending && !isActivated) { _onDetails?.(focusId, appId); return; }
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
      if (!isPending && !isActivated) { _onDetails?.(focusId, appId); return; }
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
    if (event.key === 'Escape' && isPending) {
      event.preventDefault();
      handleRejectClick();
    }
  }

  onMount(() => {
    // A clock only renders an authoritative live deadline. Expiry never activates
    // or persists focus: the server activation event owns that transition.
    countdownInterval = setInterval(() => {
      now = Date.now();
      countdownValue = Math.max(0, Math.ceil((deadline - now) / 1000));
    }, 100);

    // Listen for ESC key globally (not just when element is focused)
    document.addEventListener('keydown', handleKeydown);

    return () => {
      document.removeEventListener('keydown', handleKeydown);
      clearTouchTimer();
      if (countdownInterval) {
        clearInterval(countdownInterval);
      }
    };
  });
</script>

{#if !isRejected}
  <div
    class="focus-mode-bar"
    class:activated={isActivated}
    class:counting={isPending}
    data-testid="focus-mode-bar"
    data-focus-id={focusId}
    data-app-id={appId}
    data-embed-type="focus-mode-activation"
    role="button"
    tabindex="0"
    oncontextmenu={handleContextMenu}
    ontouchstart={handleTouchStart}
    ontouchmove={handleTouchMove}
    ontouchend={handleTouchEnd}
    onclick={handleClick}
    onkeydown={handleKeyPress}
  >
    <!-- App icon in gradient circle (matches BasicInfosBar style) -->
    <div class="app-icon-circle {appId}" style={appGradientStyle}>
      <div class="icon_rounded {appId}"></div>
    </div>

    <!-- Focus/insight skill icon (purple color for focus mode) -->
    <div class="focus-skill-icon"></div>

    <!-- Status text -->
    <div class="status-text">
      <span class="status-label" data-testid="focus-status-label">{displayName}</span>
      <span class="status-value" data-testid="focus-status-value" class:active-status={isActivated}>{statusText}</span>
    </div>

    <!-- Progress bar (only during countdown, overlaid at bottom) -->
    {#if isPending}
      <div class="progress-bar-container" data-testid="focus-progress-bar">
        <div
          class="progress-bar"
          style="width: {progressPercent}%"
        ></div>
      </div>
    {/if}
  </div>

  <!-- Helper text below the bar during countdown -->
  {#if isPending}
    <div class="reject-hint" data-testid="focus-reject-hint">
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
    gap: var(--spacing-5);
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-30);
    border-radius: 30px;
    padding: 0;
    user-select: none;
    -webkit-user-select: none;
    position: relative;
    overflow: hidden;
    transition: background-color var(--duration-normal) var(--easing-default), box-shadow var(--duration-normal) var(--easing-default);
    width: 380px;
  }

  .focus-mode-bar.counting,
  .focus-mode-bar.activated {
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
    gap: var(--spacing-1);
    padding-right: var(--spacing-8);
  }

  .focus-mode-bar .status-label {
    font-size: var(--font-size-p);
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .focus-mode-bar .status-value {
    font-size: var(--font-size-p);
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
    font-size: var(--font-size-tiny);
    color: var(--color-grey-40, #aaa);
    margin-top: var(--spacing-2);
    padding-left: var(--spacing-1);
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
