<!--
  frontend/packages/ui/src/components/embeds/FocusModeContextMenu.svelte
  
  Context menu for focus mode embeds and focus mode indicators.
  
  Shows different actions based on the current state:
  - During countdown: "Cancel" (rejects the activation) + "Details"
  - After activation: "Stop Focus Mode" (deactivates) + "Details"
  
  Follows the same patterns as EmbedContextMenu:
  - Fixed positioning with arrow indicator
  - Body-appended to escape stacking contexts
  - Callback props (not Svelte events) due to body-level rendering
  - iOS-compatible touch handling
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '@repo/ui';

  interface Props {
    /** X position of the menu (in pixels) */
    x?: number;
    /** Y position of the menu (in pixels) */
    y?: number;
    /** Whether to show the menu */
    show?: boolean;
    /** Whether the focus mode is currently activated (countdown completed) */
    isActivated?: boolean;
    /** Focus mode display name (for context) */
    focusModeName?: string;  // Passed from parent; reserved for future use in menu label
    /** Callback when menu should close */
    onClose?: () => void;
    /** Callback when Cancel/Stop action is triggered */
    onCancelOrStop?: () => void;
    /** Callback when Details action is triggered */
    onDetails?: () => void;
  }

  let {
    x = 0,
    y = 0,
    show = false,
    isActivated = false,
    focusModeName = '',
    onClose,
    onCancelOrStop,
    onDetails,
  }: Props = $props();

  // Reserved for future use in menu label (e.g., "Stop Career Insights focus mode")
  void focusModeName;

  let menuElement = $state<HTMLDivElement>();
  let adjustedX = $state(x);
  let adjustedY = $state(y);
  let showBelow = $state(false);

  /**
   * Calculate menu position to prevent cutoff at viewport edges
   */
  function calculatePosition(menuWidth: number, menuHeight: number) {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const padding = 10;
    const arrowHeight = 8;

    let newX = x;
    let newY = y;
    let shouldShowBelow = false;

    // Adjust X to prevent going off edges
    if (newX + menuWidth / 2 > viewportWidth - padding) {
      newX = viewportWidth - menuWidth / 2 - padding;
    }
    if (newX - menuWidth / 2 < padding) {
      newX = menuWidth / 2 + padding;
    }

    // Check space above/below
    const spaceAbove = y - menuHeight - arrowHeight;
    if (spaceAbove < padding) {
      shouldShowBelow = true;
      const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
      if (spaceBelow < padding) {
        if (spaceAbove > spaceBelow) {
          shouldShowBelow = false;
          newY = menuHeight + arrowHeight + padding;
        } else {
          shouldShowBelow = true;
          newY = viewportHeight - menuHeight - arrowHeight - padding;
        }
      }
    } else {
      const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
      if (spaceBelow > spaceAbove + 50) {
        shouldShowBelow = true;
      }
    }

    return { newX, newY, shouldShowBelow };
  }

  // Adjust positioning to prevent cutoff
  $effect(() => {
    if (show) {
      const estimatedWidth = 180;
      const estimatedHeight = 110;
      const initial = calculatePosition(estimatedWidth, estimatedHeight);
      adjustedX = initial.newX;
      adjustedY = initial.newY;
      showBelow = initial.shouldShowBelow;

      requestAnimationFrame(() => {
        if (!menuElement) return;
        const menuRect = menuElement.getBoundingClientRect();
        const actualWidth = menuRect.width || estimatedWidth;
        const actualHeight = menuRect.height || estimatedHeight;
        if (Math.abs(actualWidth - estimatedWidth) > 20 || Math.abs(actualHeight - estimatedHeight) > 20) {
          const refined = calculatePosition(actualWidth, actualHeight);
          adjustedX = refined.newX;
          adjustedY = refined.newY;
          showBelow = refined.shouldShowBelow;
        }
      });
    } else {
      adjustedX = x;
      adjustedY = y;
      showBelow = false;
    }
  });

  /**
   * Handle clicking outside the menu
   */
  function handleClickOutside(event: MouseEvent | TouchEvent) {
    if (menuElement && !menuElement.contains(event.target as Node)) {
      onClose?.();
    }
  }

  /**
   * Handle scroll to close menu
   */
  function handleScroll() {
    if (show) {
      onClose?.();
    }
  }

  /**
   * Handle menu button click (iOS-compatible)
   */
  function handleButtonClick(action: 'cancelOrStop' | 'details', event: Event) {
    event.stopPropagation();
    event.preventDefault();

    const callback = action === 'cancelOrStop' ? onCancelOrStop : onDetails;

    if (event.type === 'touchend') {
      setTimeout(() => {
        callback?.();
        onClose?.();
      }, 10);
    } else {
      callback?.();
      onClose?.();
    }
  }

  // Event listeners
  onMount(() => {
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('touchstart', handleClickOutside);
    document.addEventListener('scroll', handleScroll, true);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
      document.removeEventListener('scroll', handleScroll, true);
      if (menuElement && menuElement.parentNode === document.body) {
        document.body.removeChild(menuElement);
      }
    };
  });

  // Move to body to escape stacking contexts
  $effect(() => {
    if (show && menuElement) {
      tick().then(() => {
        if (menuElement && menuElement.parentNode && menuElement.parentNode !== document.body) {
          document.body.appendChild(menuElement);
        }
      });
    } else if (!show && menuElement && menuElement.parentNode === document.body) {
      document.body.removeChild(menuElement);
    }
  });
</script>

{#if show}
  <div
    class="menu-container {show ? 'show' : ''} {showBelow ? 'below' : 'above'}"
    style="--menu-x: {adjustedX}px; --menu-y: {adjustedY}px;"
    bind:this={menuElement}
  >
    <!-- Cancel/Stop action — changes label based on activation state -->
    <button
      class="menu-item cancel-stop"
      onclick={(event) => handleButtonClick('cancelOrStop', event)}
    >
      <div class="clickable-icon {isActivated ? 'icon_pause' : 'icon_close'}"></div>
      {#if isActivated}
        {$text('embeds.focus_mode.context_menu.stop', { default: 'Stop Focus Mode' })}
      {:else}
        {$text('embeds.focus_mode.context_menu.cancel', { default: 'Cancel' })}
      {/if}
    </button>

    <!-- Details action — always available -->
    <button
      class="menu-item details"
      onclick={(event) => handleButtonClick('details', event)}
    >
      <div class="clickable-icon icon_info"></div>
      {$text('embeds.context_menu.details', { default: 'Details' })}
    </button>
  </div>
{/if}

<style>
  .menu-container {
    position: fixed;
    left: var(--menu-x);
    top: var(--menu-y);
    background: var(--color-grey-blue);
    border-radius: 12px;
    padding: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    z-index: 99999;
    isolation: isolate;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease-in-out;
    min-width: 140px;
  }

  .menu-container.above {
    transform: translate(-50%, -100%);
  }

  .menu-container.below {
    transform: translate(-50%, 0);
  }

  .menu-container.show {
    opacity: 1;
    pointer-events: all;
  }

  /* Arrow pointing down (menu above click point) */
  .menu-container.above::after {
    content: '';
    position: absolute;
    bottom: -8px;
    left: 50%;
    transform: translateX(-50%);
    border-left: 8px solid transparent;
    border-right: 8px solid transparent;
    border-top: 8px solid var(--color-grey-blue);
  }

  /* Arrow pointing up (menu below click point) */
  .menu-container.below::after {
    content: '';
    position: absolute;
    top: -8px;
    left: 50%;
    transform: translateX(-50%);
    border-left: 8px solid transparent;
    border-right: 8px solid transparent;
    border-bottom: 8px solid var(--color-grey-blue);
  }

  .menu-item {
    all: unset;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    border-radius: 25px;
    cursor: pointer;
    transition: background-color 0.2s ease;
    width: 100%;
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
    -webkit-touch-callout: none;
    -webkit-user-select: none;
    user-select: none;
    min-height: 44px;
    min-width: 44px;
    white-space: nowrap;
    font-size: 14px;
    color: var(--color-grey-90);
  }

  .menu-item:hover {
    background-color: var(--color-grey-20);
  }

  .menu-item:active {
    background-color: var(--color-grey-20);
    transform: scale(0.98);
  }

  .menu-item .clickable-icon {
    width: 18px;
    height: 18px;
    min-width: 18px;
    background: var(--color-grey-70);
  }
</style>
