<!--
  frontend/packages/ui/src/components/embeds/EmbedContextMenu.svelte
  
  Context menu for embed previews (code, video, website, etc.)
  Similar to ChatContextMenu but specifically for embeds.
  
  Shows:
  - 'View' (opens fullscreen)
  - 'Share' (opens share menu)
  - All available actions from the embed (Copy, Download, etc.)
  
  Works on both mouse (right-click) and touch (long-press).
  
  IMPORTANT: This component uses callback props instead of Svelte events because
  the menu element is moved to document.body to escape stacking contexts.
  When an element is moved outside its Svelte component tree, createEventDispatcher
  events don't bubble properly to parent components' on:event handlers.
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '@repo/ui';
  import { authStore } from '../../stores/authStore';
  import { apiEndpoints, getApiEndpoint } from '../../config/api';

  /**
   * Props interface for embed context menu
   * 
   * Uses callback props (onClose, onView, etc.) instead of Svelte events
   * because the menu element is moved to document.body for z-index purposes,
   * which breaks Svelte's event dispatching system.
   */
  interface Props {
    /** X position of the menu (in pixels) */
    x?: number;
    /** Y position of the menu (in pixels) */
    y?: number;
    /** Whether to show the menu */
    show?: boolean;
    /** Embed type to determine available actions */
    embedType?: 'code' | 'video' | 'website' | 'pdf' | 'focusMode' | 'default';
    /** Whether to show View action (opens fullscreen) */
    showView?: boolean;
    /** Whether to show Share action */
    showShare?: boolean;
    /** Whether to show Copy action */
    showCopy?: boolean;
    /** Whether to show Download action */
    showDownload?: boolean;
    /** Whether to show Deactivate action (for focus mode embeds) */
    showDeactivate?: boolean;
    /** Whether to show Details action (for focus mode embeds) */
    showDetails?: boolean;
    /** Message ID for fetching credit cost (optional) */
    messageId?: string;
    /** Callback when menu should close */
    onClose?: () => void;
    /** Callback when View action is triggered */
    onView?: () => void;
    /** Callback when Share action is triggered */
    onShare?: () => void;
    /** Callback when Copy action is triggered */
    onCopy?: () => void;
    /** Callback when Download action is triggered */
    onDownload?: () => void;
    /** Callback when Deactivate action is triggered (focus mode) */
    onDeactivate?: () => void;
    /** Callback when Details action is triggered (focus mode) */
    onDetails?: () => void;
  }

  let {
    x = 0,
    y = 0,
    show = false,
    // embedType is accepted for future use but not currently used
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    embedType = 'default',
    showView = true,
    showShare = true,
    showCopy = false,
    showDownload = false,
    showDeactivate = false,
    showDetails = false,
    messageId = undefined,
    onClose,
    onView,
    onShare,
    onCopy,
    onDownload,
    onDeactivate,
    onDetails
  }: Props = $props();
  
  // State for embed credits (fetched from usage API)
  let embedCredits = $state<number | null>(null);
  
  // Format credits with dots as thousand separators (European style)
  function formatCredits(credits: number): string {
    return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }
  
  // Fetch embed credits when menu is shown (only for authenticated users with messageId)
  $effect(() => {
    if (show && messageId && $authStore.isAuthenticated) {
      const endpoint = `${getApiEndpoint(apiEndpoints.usage.messageCost)}?message_id=${encodeURIComponent(messageId)}`;
      fetch(endpoint, { credentials: 'include' })
        .then(res => res.ok ? res.json() : null)
        .then(data => {
          if (data && typeof data.credits === 'number') {
            embedCredits = data.credits;
          } else {
            embedCredits = null;
          }
        })
        .catch(() => {
          embedCredits = null;
        });
    } else {
      embedCredits = null;
    }
  });

  let menuElement = $state<HTMLDivElement>();
  let adjustedX = $state(x);
  let adjustedY = $state(y);
  let showBelow = $state(false); // Track whether menu should appear below clicked point

  /**
   * Calculate menu position to prevent cutoff at viewport edges
   */
  function calculatePosition(menuWidth: number, menuHeight: number) {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const padding = 10; // Minimum distance from viewport edges
    const arrowHeight = 8; // Height of the arrow

    let newX = x;
    let newY = y;
    let shouldShowBelow = false;

    // Adjust X if it goes off the right edge
    if (newX + menuWidth / 2 > viewportWidth - padding) {
      newX = viewportWidth - menuWidth / 2 - padding;
    }
    // Adjust X if it goes off the left edge
    if (newX - menuWidth / 2 < padding) {
      newX = menuWidth / 2 + padding;
    }

    // Check if there's enough space above the clicked point
    // Menu appears above by default (transform: translate(-50%, -100%))
    const spaceAbove = y - menuHeight - arrowHeight;
    
    if (spaceAbove < padding) {
      // Not enough space above, show below instead
      shouldShowBelow = true;
      // Check if there's enough space below
      const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
      if (spaceBelow < padding) {
        // Not enough space below either, position at viewport edge
        if (spaceAbove > spaceBelow) {
          // More space above, show above but adjust Y
          shouldShowBelow = false;
          newY = menuHeight + arrowHeight + padding;
        } else {
          // More space below, show below but adjust Y
          shouldShowBelow = true;
          newY = viewportHeight - menuHeight - arrowHeight - padding;
        }
      }
    } else {
      // Enough space above, check if we should still show below for better UX
      const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
      // Only show below if there's significantly more space below
      if (spaceBelow > spaceAbove + 50) {
        shouldShowBelow = true;
      }
    }

    return { newX, newY, shouldShowBelow };
  }

  // Adjust positioning to prevent cutoff
  $effect(() => {
    if (show) {
      // First, calculate with estimated dimensions to prevent visual jump
      const estimatedWidth = 150;
      const estimatedHeight = 100;
      const initial = calculatePosition(estimatedWidth, estimatedHeight);
      adjustedX = initial.newX;
      adjustedY = initial.newY;
      showBelow = initial.shouldShowBelow;

      // Then refine with actual dimensions after render
      requestAnimationFrame(() => {
        if (!menuElement) return;
        
        const menuRect = menuElement.getBoundingClientRect();
        const actualWidth = menuRect.width || estimatedWidth;
        const actualHeight = menuRect.height || estimatedHeight;
        
        // Only recalculate if dimensions differ significantly
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
   * Action type for menu items
   */
  type MenuAction = 'view' | 'share' | 'copy' | 'download' | 'deactivate' | 'details';

  /**
   * Get the callback for a given action
   */
  function getActionCallback(action: MenuAction): (() => void) | undefined {
    switch (action) {
      case 'view': return onView;
      case 'share': return onShare;
      case 'copy': return onCopy;
      case 'download': return onDownload;
      case 'deactivate': return onDeactivate;
      case 'details': return onDetails;
      default: return undefined;
    }
  }

  /**
   * Unified handler for both mouse and touch events
   * Calls the appropriate callback prop and then closes the menu
   */
  function handleMenuAction(action: MenuAction, event: MouseEvent | TouchEvent) {
    event.stopPropagation();
    event.preventDefault();

    console.debug('[EmbedContextMenu] Menu action triggered:', action, 'Event type:', event.type);

    // Call the action callback
    const callback = getActionCallback(action);
    callback?.();
    
    // Close the menu
    onClose?.();
  }

  /**
   * Single event handler that works for all input types (iOS-compatible)
   */
  function handleButtonClick(action: MenuAction, event: Event) {
    event.stopPropagation();
    event.preventDefault();
    
    console.debug('[EmbedContextMenu] Button click handled:', action, 'Event type:', event.type);
    
    // Handle the action with appropriate delay for touch events
    if (event.type === 'touchend') {
      setTimeout(() => {
        handleMenuAction(action, event as TouchEvent);
      }, 10);
    } else {
      handleMenuAction(action, event as MouseEvent);
    }
  }

  /**
   * Add scroll handler to close menu on scroll
   */
  function handleScroll() {
    if (show) {
      onClose?.();
    }
  }

  // Add and remove event listeners
  onMount(() => {
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('touchstart', handleClickOutside);
    document.addEventListener('scroll', handleScroll, true);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
      document.removeEventListener('scroll', handleScroll, true);
      // Cleanup: remove menu from body if it's still there
      if (menuElement && menuElement.parentNode === document.body) {
        document.body.removeChild(menuElement);
      }
    };
  });

  // Render menu at body level to avoid stacking context issues
  // Move the menu element to document.body when shown to escape any parent stacking contexts
  $effect(() => {
    if (show && menuElement) {
      // Wait for element to be rendered in DOM first, then move to body
      tick().then(() => {
        if (menuElement && menuElement.parentNode && menuElement.parentNode !== document.body) {
          // Move to body to escape stacking context
          document.body.appendChild(menuElement);
        }
      });
    } else if (!show && menuElement && menuElement.parentNode === document.body) {
      // Cleanup: remove from body when hidden
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
    <!-- Credits display - shown when available (fetched from usage API) -->
    {#if embedCredits !== null && embedCredits > 0}
      <div class="embed-credits">
        <div class="clickable-icon icon_coins"></div>
        {formatCredits(embedCredits)} {$text('chats.context_menu.credits', { default: 'credits' })}
      </div>
    {/if}
    
    <!-- View action - opens fullscreen -->
    {#if showView}
      <button
        class="menu-item view"
        onclick={(event) => handleButtonClick('view', event)}
      >
        <div class="clickable-icon icon_fullscreen"></div>
        {$text('embeds.context_menu.view', { default: 'View' })}
      </button>
    {/if}

    <!-- Share action - opens share menu -->
    {#if showShare}
      <button
        class="menu-item share"
        onclick={(event) => handleButtonClick('share', event)}
      >
        <div class="clickable-icon icon_share"></div>
        {$text('embeds.context_menu.share', { default: 'Share' })}
      </button>
    {/if}

    <!-- Copy action - copies embed content/URL -->
    {#if showCopy}
      <button
        class="menu-item copy"
        onclick={(event) => handleButtonClick('copy', event)}
      >
        <div class="clickable-icon icon_copy"></div>
        {$text('embeds.context_menu.copy', { default: 'Copy' })}
      </button>
    {/if}

    <!-- Download action - downloads embed content -->
    {#if showDownload}
      <button
        class="menu-item download"
        onclick={(event) => handleButtonClick('download', event)}
      >
        <div class="clickable-icon icon_download"></div>
        {$text('embeds.context_menu.download', { default: 'Download' })}
      </button>
    {/if}

    <!-- Deactivate action - deactivates focus mode (focus mode embeds only) -->
    {#if showDeactivate}
      <button
        class="menu-item deactivate"
        onclick={(event) => handleButtonClick('deactivate', event)}
      >
        <div class="clickable-icon icon_pause"></div>
        {$text('embeds.context_menu.deactivate', { default: 'Deactivate' })}
      </button>
    {/if}

    <!-- Details action - opens focus mode details in app store (focus mode embeds only) -->
    {#if showDetails}
      <button
        class="menu-item details"
        onclick={(event) => handleButtonClick('details', event)}
      >
        <div class="clickable-icon icon_info"></div>
        {$text('embeds.context_menu.details', { default: 'Details' })}
      </button>
    {/if}
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
    z-index: 99999; /* Very high z-index to ensure it's above everything */
    isolation: isolate; /* Create new stacking context */
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease-in-out;
    min-width: 120px;
  }

  /* Position menu above clicked point (default) */
  .menu-container.above {
    transform: translate(-50%, -100%);
  }

  /* Position menu below clicked point */
  .menu-container.below {
    transform: translate(-50%, 0);
  }

  .menu-container.show {
    opacity: 1;
    pointer-events: all;
  }

  /* Arrow pointing down (when menu is above clicked point) */
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

  /* Arrow pointing up (when menu is below clicked point) */
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

  /* Embed credits displayed above the action buttons */
  .embed-credits {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    margin-bottom: 4px;
    color: var(--color-grey-50);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    border-bottom: 1px solid var(--color-grey-30);
  }
  
  .embed-credits .clickable-icon {
    width: 14px;
    height: 14px;
    background: var(--color-grey-50);
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
    /* iOS-specific touch improvements */
    -webkit-tap-highlight-color: transparent;
    -webkit-touch-callout: none;
    -webkit-user-select: none;
    user-select: none;
    /* Ensure proper touch target size for iOS */
    min-height: 44px;
    min-width: 44px;
  }

  .menu-item:hover {
    background-color: var(--color-grey-20);
  }

  /* iOS touch feedback */
  .menu-item:active {
    background-color: var(--color-grey-20);
    transform: scale(0.98);
  }
</style>



