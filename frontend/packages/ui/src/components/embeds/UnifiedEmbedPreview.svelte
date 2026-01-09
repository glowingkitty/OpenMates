<!--
  frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
  
  Unified base component for all embed previews (app skills, websites, etc.)
  
  Structure according to Figma design:
  - Details section (top) - skill-specific content via snippet
  - basic_infos bar (bottom) - standardized layout with:
    - App icon in gradient circle (61x61px container, 26x26px icon)
    - Skill icon (29x29px)
    - Status text (skill name + processing status)
    - Stop button (when processing)
  
  Sizes:
  - Desktop: 300x200px
  - Mobile: 150x290px
  
  Interactive States (finished embeds only):
  - Clickable cursor (pointer) on hover
  - 3D tilt effect: tilts towards mouse position (max 3 degrees, subtle)
  - Scale down to 98.5% on hover, 96% on active/click
  - Enhanced box-shadow on hover for depth effect
  - Smooth transitions for all hover effects
  - Mouse-only: does not apply on touch devices (no hover concept)
  
  CRITICAL: This component subscribes to embedUpdated events to receive
  real-time updates when embed status changes from 'processing' to 'finished'.
  This is necessary because Svelte components mounted via mount() receive
  static props - they don't automatically update when embed data changes.
  
  The component notifies child preview components of updates via the
  onEmbedDataUpdated callback, allowing them to update their specific data
  (like search results, query text, etc.).
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import BasicInfosBar from './BasicInfosBar.svelte';
  import { chatSyncService } from '../../services/chatSyncService';
  import { embedStore } from '../../services/embedStore';
  import { decodeToonContent } from '../../services/embedResolver';
  
  /**
   * Props interface for unified embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** App identifier (e.g., 'web', 'videos', 'code') - used for gradient color */
    appId: string;
    /** Skill identifier (e.g., 'search', 'get_transcript') */
    skillId: string;
    /** Icon name for the skill icon (e.g., 'search', 'videos', 'book') - passed from skill-specific components */
    skillIconName: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Skill display name (shown in basic_infos bar) */
    skillName: string;
    /** Optional task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
    /** Click handler for stop button */
    onStop?: () => void;
    /** Snippet for details content (skill-specific) - REQUIRED but made optional for defensive programming */
    details?: import('svelte').Snippet<[{ isMobile: boolean }]>;
    /** Whether to show status line in basic infos bar (default: true) */
    showStatus?: boolean;
    /** Custom favicon URL for basic infos bar (shows instead of app icon) */
    faviconUrl?: string;
    /** Whether favicon should be circular (for channel thumbnails, profile pics) */
    faviconIsCircular?: boolean;
    /** Custom status text (overrides default status text) */
    customStatusText?: string;
    /** Whether to show skill icon (only for app skills, not for individual embeds like code, website, video) */
    showSkillIcon?: boolean;
    /** Whether the details content contains a full-width image (removes padding, adds negative margin) */
    hasFullWidthImage?: boolean;
    /** Callback when embed data is updated - allows child components to update their specific data */
    onEmbedDataUpdated?: (data: { status: string; decodedContent: any }) => void;
  }
  
  let {
    id,
    appId,
    skillId,
    skillIconName,
    status: statusProp,
    skillName,
    taskId,
    isMobile = false,
    onFullscreen,
    onStop,
    details,
    showStatus = true,
    faviconUrl,
    faviconIsCircular = false,
    customStatusText,
    showSkillIcon = true,
    hasFullWidthImage = false,
    onEmbedDataUpdated
  }: Props = $props();
  
  // Local reactive state for status - can be updated when embedUpdated fires
  // This overrides the prop when we receive updates from the server
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  
  // Initialize local status from prop
  $effect(() => {
    localStatus = statusProp || 'processing';
  });
  
  // Use local status as the source of truth (allows updates from embed events)
  let status = $derived(localStatus);
  
  /**
   * Handle embed updates from chatSyncService
   * When an embedUpdated event fires for this embed ID, refetch data from store
   */
  function handleEmbedUpdate(event: CustomEvent) {
    const { embed_id, status: newStatus } = event.detail;
    
    // Only process updates for this specific embed
    if (embed_id !== id) {
      return;
    }
    
    console.debug(`[UnifiedEmbedPreview] 🔄 Received embedUpdated for ${id}:`, {
      newStatus,
      previousStatus: localStatus
    });
    
    // Update status immediately from event if provided
    if (newStatus && (newStatus === 'processing' || newStatus === 'finished' || newStatus === 'error' || newStatus === 'cancelled')) {
      localStatus = newStatus;
    }
    
    // Refetch from store to get full data and notify child components
    refetchFromStore();
  }
  
  /**
   * Refetch embed data from the store
   * This ensures we have the latest data after an update
   * and notifies child components via onEmbedDataUpdated callback
   * 
   * NOTE: Skips fetch for "legacy-*" IDs which are synthetic IDs created by
   * transformLegacyResults() in search fullscreens. These IDs don't exist in
   * IndexedDB - the data is already available from the parent component's props.
   */
  async function refetchFromStore() {
    // Skip refetch for legacy IDs - these are synthetic IDs from legacy results
    // that don't exist in IndexedDB. The data is already available from props.
    if (id.startsWith('legacy-')) {
      console.debug(`[UnifiedEmbedPreview] Skipping refetch for synthetic legacy ID: ${id}`);
      return;
    }
    
    try {
      const embedData = await embedStore.get(`embed:${id}`);
      if (embedData) {
        console.debug(`[UnifiedEmbedPreview] Refetched data from store for ${id}:`, {
          status: embedData.status,
          hasContent: !!embedData.content
        });
        
        // Update status from fetched data
        if (embedData.status && (embedData.status === 'processing' || embedData.status === 'finished' || embedData.status === 'error' || embedData.status === 'cancelled')) {
          localStatus = embedData.status;
        }
        
        // Decode content and notify child component if callback is provided
        if (onEmbedDataUpdated && embedData.content) {
          const decodedContent = await decodeToonContent(embedData.content);
          if (decodedContent) {
            onEmbedDataUpdated({
              status: embedData.status || localStatus,
              decodedContent
            });
          }
        }
      }
    } catch (error) {
      console.error(`[UnifiedEmbedPreview] Error refetching from store for ${id}:`, error);
    }
  }
  
  // Subscribe to embedUpdated events on mount
  let embedUpdateListener: EventListener | null = null;
  
  onMount(() => {
    console.debug(`[UnifiedEmbedPreview] Mounted component for embed ${id}`);
    
    // Subscribe to embedUpdated events from chatSyncService
    embedUpdateListener = handleEmbedUpdate as EventListener;
    chatSyncService.addEventListener('embedUpdated', embedUpdateListener);
    
    // Do an initial fetch to ensure we have the latest data
    // (in case the embed was updated between render and mount)
    refetchFromStore();
  });
  
  onDestroy(() => {
    // Clean up event listener
    if (embedUpdateListener) {
      chatSyncService.removeEventListener('embedUpdated', embedUpdateListener);
      embedUpdateListener = null;
    }
    
    // Clean up context menu reset timer
    if (contextMenuResetTimer) {
      clearTimeout(contextMenuResetTimer);
      contextMenuResetTimer = null;
    }
  });
  
  // DEBUG: Log when details snippet is missing - this helps identify which embed is broken
  $effect(() => {
    if (!details) {
      console.error('[UnifiedEmbedPreview] MISSING details snippet! This will cause rendering issues.', {
        id,
        appId,
        skillId,
        skillName,
        status
      });
    }
  });
  
  // Determine layout based on isMobile prop only
  // Mobile layout should only be used inside groups of embedded previews
  // when the surrounding container width gets too small (set by parent component)
  // Otherwise, desktop layout is used by default
  let useMobileLayout = $derived(isMobile);
  
  // Reference to the preview element for transition calculations
  let previewElement = $state<HTMLElement | null>(null);
  
  // Track if we're handling a context menu to prevent normal click from firing
  // This flag prevents a right-click from also triggering a left-click action
  let isContextMenuHandled = $state(false);
  
  // Timer to auto-reset isContextMenuHandled after context menu closes
  // This ensures the flag doesn't "stick" and block future clicks
  let contextMenuResetTimer: ReturnType<typeof setTimeout> | null = null;
  
  /**
   * Reset the context menu handled flag and clear any pending timer
   * Called when we want to allow normal click handling again
   */
  function resetContextMenuFlag() {
    isContextMenuHandled = false;
    if (contextMenuResetTimer) {
      clearTimeout(contextMenuResetTimer);
      contextMenuResetTimer = null;
    }
  }
  
  /**
   * Mark that a context menu is being handled and schedule auto-reset
   * The auto-reset ensures the flag doesn't block clicks if the menu closes
   * without an action (e.g., clicking elsewhere to dismiss)
   */
  function markContextMenuHandled() {
    isContextMenuHandled = true;
    
    // Clear any existing timer
    if (contextMenuResetTimer) {
      clearTimeout(contextMenuResetTimer);
    }
    
    // Auto-reset after a short delay
    // This gives enough time for the context menu to capture clicks,
    // but ensures we don't permanently block normal clicks if the menu
    // closes without an action (e.g., clicking elsewhere to dismiss)
    contextMenuResetTimer = setTimeout(() => {
      isContextMenuHandled = false;
      contextMenuResetTimer = null;
    }, 300);
  }
  
  // ===========================================
  // Mouse tracking for tilt effect (3D hover)
  // ===========================================
  
  // Track hover state and mouse position for tilt effect
  let isHovering = $state(false);
  let mouseX = $state(0); // Normalized -1 to 1 (center = 0)
  let mouseY = $state(0); // Normalized -1 to 1 (center = 0)
  
  // Configuration for the tilt effect
  // NOTE: Keep values subtle for a polished feel without being distracting
  const TILT_MAX_ANGLE = 3; // Maximum tilt angle in degrees (subtle effect)
  const TILT_PERSPECTIVE = 800; // Perspective distance in pixels (higher = more subtle)
  const TILT_SCALE = 0.985; // Scale on hover (closer to 1 = more subtle)
  
  /**
   * Calculate CSS transform string for the 3D tilt effect
   * Only applies when hovering over a finished embed
   */
  let tiltTransform = $derived.by(() => {
    // Only apply tilt to finished embeds that are being hovered
    if (!isHovering || status !== 'finished') {
      return '';
    }
    
    // Calculate rotation angles based on mouse position
    // mouseX/Y are normalized to -1 to 1, where center is 0
    // Positive mouseX (right side) -> rotate Y positive (tilt right edge away)
    // Positive mouseY (bottom) -> rotate X negative (tilt bottom edge away)
    const rotateY = mouseX * TILT_MAX_ANGLE;
    const rotateX = -mouseY * TILT_MAX_ANGLE;
    
    return `perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TILT_SCALE})`;
  });
  
  /**
   * Handle mouse enter - start tracking for tilt effect
   */
  function handleMouseEnter(e: MouseEvent) {
    if (status !== 'finished') return;
    isHovering = true;
    updateMousePosition(e);
  }
  
  /**
   * Handle mouse move - update tilt position
   */
  function handleMouseMove(e: MouseEvent) {
    if (!isHovering || status !== 'finished' || !previewElement) return;
    updateMousePosition(e);
  }
  
  /**
   * Handle mouse leave - reset tilt effect
   */
  function handleMouseLeave() {
    isHovering = false;
    mouseX = 0;
    mouseY = 0;
  }
  
  /**
   * Update mouse position normalized to -1 to 1 range
   * Center of element = (0, 0), edges = (-1/-1 to 1/1)
   */
  function updateMousePosition(e: MouseEvent) {
    if (!previewElement) return;
    
    const rect = previewElement.getBoundingClientRect();
    // Normalize to -1 to 1 range (center = 0)
    mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
  }
  
  // Touch event handlers for long-press detection (mobile support)
  const LONG_PRESS_DURATION = 500; // milliseconds
  const TOUCH_MOVE_THRESHOLD = 10; // pixels
  
  let touchTimer: ReturnType<typeof setTimeout> | null = null;
  let touchStartX = 0;
  let touchStartY = 0;
  let touchTarget: HTMLElement | null = null;
  
  /**
   * Handle touch start for long-press detection
   * Starts a timer that will trigger context menu if touch is held long enough
   */
  function handleTouchStart(e: TouchEvent) {
    // Prevent TipTap / parent handlers from interfering with embed interactions
    e.stopPropagation();
    
    // Only handle single touch
    if (e.touches.length !== 1) {
      clearTouchTimer();
      return;
    }
    
    const touch = e.touches[0];
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;
    touchTarget = previewElement;
    
    // Start long-press timer
    touchTimer = setTimeout(() => {
      if (touchTarget && previewElement) {
        console.debug('[UnifiedEmbedPreview] Long-press detected - triggering context menu');
        
        // Mark that we're handling a context menu (with auto-reset)
        markContextMenuHandled();
        
        // Get container rect for menu positioning
        const rect = previewElement.getBoundingClientRect();
        
        // Dispatch a custom event that ReadOnlyMessage can listen to
        // This allows the context menu to be shown at the embed level
        const contextMenuEvent = new CustomEvent('embed-context-menu', {
          bubbles: true,
          cancelable: true,
          detail: {
            embedId: id,
            appId,
            skillId,
            rect: {
              left: rect.left,
              top: rect.top,
              width: rect.width,
              height: rect.height
            },
            x: touchStartX,
            y: touchStartY
          }
        });
        
        previewElement.dispatchEvent(contextMenuEvent);
        
        // Vibrate to provide haptic feedback (if supported)
        if (navigator.vibrate) {
          navigator.vibrate(50);
        }
      }
    }, LONG_PRESS_DURATION);
  }
  
  /**
   * Handle touch move - cancel long-press if finger moves too much
   */
  function handleTouchMove(e: TouchEvent) {
    e.stopPropagation();
    if (!touchTimer || e.touches.length !== 1) {
      return;
    }
    
    const touch = e.touches[0];
    const deltaX = Math.abs(touch.clientX - touchStartX);
    const deltaY = Math.abs(touch.clientY - touchStartY);
    
    // If finger moved too much, cancel the long-press
    if (deltaX > TOUCH_MOVE_THRESHOLD || deltaY > TOUCH_MOVE_THRESHOLD) {
      clearTouchTimer();
    }
  }
  
  /**
   * Handle touch end - cancel long-press timer
   */
  function handleTouchEnd(e: TouchEvent) {
    e.stopPropagation();
    clearTouchTimer();
  }
  
  /**
   * Clear the touch timer
   */
  function clearTouchTimer() {
    if (touchTimer) {
      clearTimeout(touchTimer);
      touchTimer = null;
    }
    touchTarget = null;
  }
  
  // Handle click to open fullscreen (only when finished)
  // Store preview element position for transition animation
  // CRITICAL: Stop event propagation to prevent ReadOnlyMessage from showing context menu
  // BUT: Don't stop context menu events - let them bubble up for proper context menu handling
  function handleClick(e: MouseEvent) {
    // If this was triggered right after a context menu opened, skip this click
    // The context menu flag auto-resets after 300ms, so this only blocks the
    // immediate click that might fire alongside the right-click
    if (isContextMenuHandled) {
      resetContextMenuFlag();
      return;
    }
    
    console.debug('[UnifiedEmbedPreview] Click handler called:', { 
      status, 
      hasOnFullscreen: !!onFullscreen,
      embedId: id,
      eventType: e.type,
      target: e.target
    });
    
    // Stop event propagation to prevent the click from bubbling to ReadOnlyMessage
    // which would show the context menu instead of opening fullscreen
    // NOTE: We don't call preventDefault() here because it might interfere with the click
    e.stopPropagation();
    
    if (status === 'finished' && onFullscreen) {
      console.debug('[UnifiedEmbedPreview] Calling onFullscreen for embed:', id);
      
      // Store the preview element's position for transition
      if (previewElement) {
        const rect = previewElement.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        
        // Store position in a data attribute that UnifiedEmbedFullscreen can read
        // This allows the fullscreen to animate from the preview position
        document.documentElement.style.setProperty('--preview-center-x', `${centerX}px`);
        document.documentElement.style.setProperty('--preview-center-y', `${centerY}px`);
        document.documentElement.style.setProperty('--preview-width', `${rect.width}px`);
        document.documentElement.style.setProperty('--preview-height', `${rect.height}px`);
      }
      
      try {
        onFullscreen();
        console.debug('[UnifiedEmbedPreview] onFullscreen called successfully');
      } catch (error) {
        console.error('[UnifiedEmbedPreview] Error calling onFullscreen:', error);
      }
    } else {
      console.warn('[UnifiedEmbedPreview] Cannot open fullscreen:', { 
        status, 
        hasOnFullscreen: !!onFullscreen 
      });
    }
  }
  
  // Stop mousedown from bubbling to TipTap node view handlers (which can interfere with fullscreen opening)
  function handleMouseDown(e: MouseEvent) {
    e.stopPropagation();
  }
  
  // Pointer events can fire before click on some platforms (and can trigger parent handlers)
  function handlePointerDown(e: PointerEvent) {
    e.stopPropagation();
  }
  
  /**
   * Handle right-click context menu
   * Allow the event to bubble up to ReadOnlyMessage for proper context menu handling
   * Only prevent default browser context menu
   */
  function handleContextMenu(e: MouseEvent) {
    // Always prevent native browser context menu inside embeds.
    e.preventDefault();
    // Stop bubbling to TipTap's contextmenu handler to avoid duplicate menu triggers.
    e.stopPropagation();
    
    // Mark that we're handling a context menu to prevent normal click from firing
    // Uses auto-reset to ensure flag doesn't block clicks if menu closes without action
    markContextMenuHandled();
    
    // Dispatch a custom event that ReadOnlyMessage can listen to.
    // This ensures right-click always opens EmbedContextMenu (and not the browser menu).
    if (previewElement) {
      const rect = previewElement.getBoundingClientRect();
      const contextMenuEvent = new CustomEvent('embed-context-menu', {
        bubbles: true,
        cancelable: true,
        detail: {
          embedId: id,
          appId,
          skillId,
          rect: {
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height
          },
          x: e.clientX,
          y: e.clientY
        }
      });
      previewElement.dispatchEvent(contextMenuEvent);
    }
  }
  
  // Handle keyboard navigation
  function handleKeydown(e: KeyboardEvent) {
    if ((e.key === 'Enter' || e.key === ' ') && status === 'finished') {
      e.preventDefault();
      // Create a synthetic mouse event for handleClick
      const syntheticEvent = new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
        view: window
      });
      handleClick(syntheticEvent);
    }
  }
  
  // Handle stop button click - prevent event propagation
  // Wrapper for BasicInfosBar onStop prop (it expects () => void)
  function handleStop() {
    if (onStop) {
      onStop();
    }
  }
</script>

<div
  bind:this={previewElement}
  class="unified-embed-preview"
  class:mobile={useMobileLayout}
  class:desktop={!useMobileLayout}
  class:processing={status === 'processing'}
  class:finished={status === 'finished'}
  class:hovering={isHovering && status === 'finished'}
  class:error={status === 'error'}
  data-embed-id={id}
  data-app-id={appId}
  data-skill-id={skillId}
  data-status={status}
  style={tiltTransform ? `transform: ${tiltTransform};` : ''}
  {...(status === 'finished' ? {
    role: 'button',
    tabindex: 0,
    onclick: handleClick,
    onkeydown: handleKeydown
  } : {
    role: 'presentation'
  })}
  onpointerdown={handlePointerDown}
  onmousedown={handleMouseDown}
  onmouseenter={handleMouseEnter}
  onmousemove={handleMouseMove}
  onmouseleave={handleMouseLeave}
  oncontextmenu={handleContextMenu}
  ontouchstart={handleTouchStart}
  ontouchmove={handleTouchMove}
  ontouchend={handleTouchEnd}
>
  {#if useMobileLayout}
    <!-- Mobile Layout: Vertical card (150x290px) -->
    <div class="mobile-layout">
      <!-- Details content (skill-specific) - with defensive guard -->
      <div class="details-section">
        {#if details}
          {@render details({ isMobile: true })}
        {:else}
          <!-- Fallback when details snippet is missing -->
          <div class="missing-details-fallback">
            <span class="fallback-text">{skillName || appId}</span>
          </div>
        {/if}
      </div>
      
      <!-- Basic infos bar (mobile layout) -->
      <BasicInfosBar
        {appId}
        {skillId}
        {skillIconName}
        {status}
        {skillName}
        {taskId}
        isMobile={true}
        onStop={handleStop}
        {showStatus}
        {faviconUrl}
        {faviconIsCircular}
        {showSkillIcon}
        customStatusText={customStatusText}
      />
    </div>
  {:else}
    <!-- Desktop Layout: Horizontal card (300x200px) -->
    <div class="desktop-layout">
      <!-- Details content (skill-specific) at top - with defensive guard -->
      <div class="details-section" class:full-width-image={hasFullWidthImage}>
        {#if details}
          {@render details({ isMobile: false })}
        {:else}
          <!-- Fallback when details snippet is missing -->
          <div class="missing-details-fallback">
            <span class="fallback-text">{skillName || appId}</span>
          </div>
        {/if}
      </div>
      
      <!-- Basic infos bar (desktop layout) -->
      <BasicInfosBar
        {appId}
        {skillId}
        {skillIconName}
        {status}
        {skillName}
        {taskId}
        isMobile={false}
        onStop={handleStop}
        {showStatus}
        {faviconUrl}
        {faviconIsCircular}
        {showSkillIcon}
        customStatusText={customStatusText}
      />
    </div>
  {/if}
</div>

<style>
  /* ===========================================
     Unified Embed Preview - Base Container
     =========================================== */
  
  .unified-embed-preview {
    position: relative;
    background-color: var(--color-grey-25);
    border-radius: 30px;
    /* Base shadow: element "floats" above surface → larger, softer shadow */
    /* Using two layers: soft ambient shadow + contact shadow */
    box-shadow: 
      0 8px 24px rgba(0, 0, 0, 0.16),
      0 2px 6px rgba(0, 0, 0, 0.1);
    /* Smooth transition for transform (tilt effect) and box-shadow (hover glow) */
    /* Using ease-out for snappy response on hover start, smooth return on leave */
    transition: 
      transform 0.15s ease-out,
      box-shadow 0.2s ease-out,
      background-color 0.2s ease;
    overflow: hidden;
    box-sizing: border-box;
    /* Prevent selection/callouts inside embeds; embeds behave as one interactive element. */
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    /* Performance hint for transform animations */
    will-change: transform;
  }
  
  /* Prevent image drag/callouts */
  .unified-embed-preview :global(img) {
    -webkit-user-drag: none;
    user-drag: none;
  }
  
  /* Finished embeds act like a single button: children shouldn't capture pointer events. */
  .unified-embed-preview.finished .desktop-layout,
  .unified-embed-preview.finished .mobile-layout {
    pointer-events: none;
  }
  
  /* Desktop layout: 300x200px */
  .unified-embed-preview.desktop {
    width: 300px;
    min-width: 300px;
    max-width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
  }
  
  /* Mobile layout: 150x290px */
  .unified-embed-preview.mobile {
    width: 150px;
    min-width: 150px;
    max-width: 150px;
    height: 290px;
    min-height: 290px;
    max-height: 290px;
  }
  
  /* Interactive state for finished previews */
  .unified-embed-preview.finished {
    /* Ensure clickable cursor is always shown */
    cursor: pointer !important;
  }
  
  /* Hovering state (controlled by JS for tilt effect) */
  .unified-embed-preview.finished.hovering {
    /* Pressed down → closer to surface → tighter, smaller shadow */
    box-shadow: 
      0 4px 12px rgba(0, 0, 0, 0.12),
      0 1px 3px rgba(0, 0, 0, 0.08);
  }
  
  /* CSS fallback hover for non-JS scenarios (shouldn't normally apply) */
  .unified-embed-preview.finished:hover:not(.hovering) {
    transform: scale(0.98);
    /* Match the hovering shadow for consistency */
    box-shadow: 
      0 4px 12px rgba(0, 0, 0, 0.12),
      0 1px 3px rgba(0, 0, 0, 0.08);
  }
  
  .unified-embed-preview.finished:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* Active/pressed state */
  .unified-embed-preview.finished:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }
  
  /* Error state */
  .unified-embed-preview.error {
    border: 1px solid var(--color-error);
    background-color: rgba(var(--color-error-rgb), 0.1);
  }
  
  /* ===========================================
     Desktop Layout
     =========================================== */
  
  .desktop-layout {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  
  .desktop-layout .details-section {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  
  /* Default padding for text-based content */
  .desktop-layout .details-section:not(.full-width-image) {
    padding-right: 20px;
    padding-left: 20px;
  }
  
  /* Full-width image content: remove padding and add negative margin at bottom */
  /* The negative margin allows the image to extend into the BasicInfosBar area */
  /* to fill the rounded corners and reach approximately the center of the bar */
  /* BasicInfosBar is 61px tall, so -55px extends roughly to its center */
  .desktop-layout .details-section.full-width-image {
    padding-right: 0;
    padding-left: 0;
    margin-bottom: -55px;
  }
  
  /* ===========================================
     Mobile Layout
     =========================================== */
  
  .mobile-layout {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 13px;
    gap: 8px;
    align-items: center;
  }
  
  .mobile-layout .details-section {
    width: 100%;
    flex: 1;
    min-height: 0;
  }
  
  /* ===========================================
     Fallback for Missing Details Snippet
     =========================================== */
  
  .missing-details-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    padding: 16px;
    color: var(--color-grey-70);
    font-size: 14px;
    text-align: center;
  }
  
  .fallback-text {
    word-break: break-word;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
  }
</style>
