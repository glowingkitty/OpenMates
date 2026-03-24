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
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  
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
    /** Click handler for fullscreen — REQUIRED: every embed must have a fullscreen version */
    onFullscreen: () => void;
    /** Click handler for stop button */
    onStop?: () => void;
    /** Snippet for details content (skill-specific) - REQUIRED but made optional for defensive programming */
    details?: import('svelte').Snippet<[{ isMobile: boolean; isLarge?: boolean }]>;
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
    /**
     * Override the fixed card height (px value, e.g. 350).
     * Used for portrait/vertical images so the full image height is visible
     * instead of being cropped. Only affects the desktop layout.
     */
    customHeight?: number;
    /** Callback when embed data is updated - allows child components to update their specific data */
    onEmbedDataUpdated?: (data: { status: string; decodedContent: Record<string, unknown> }) => void;
    /** Optional snippet rendered before the title text in BasicInfosBar (e.g., category circle) */
    titleIcon?: import('svelte').Snippet;
    /** Optional snippet rendered between the app icon and the status text in BasicInfosBar (e.g., play button for audio) */
    actionButton?: import('svelte').Snippet;
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
    customHeight,
    onEmbedDataUpdated,
    titleIcon,
    actionButton
  }: Props = $props();
  
  // Local reactive state for status - can be updated when embedUpdated fires
  // This overrides the prop when we receive updates from the server
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');

  // Track whether the store has resolved a definitive status for this embed.
  // Once the store says "finished", the $effect must NOT revert to statusProp
  // (which may still be "processing" from the HTML attribute baked during streaming).
  let storeResolved = $state(false);

  // Initialize local status from prop — but only when the store hasn't resolved yet.
  // After refetchFromStore() or an embedUpdated event sets a terminal status,
  // the prop is ignored to prevent re-mount from reverting "finished" → "processing".
  $effect(() => {
    if (!storeResolved) {
      localStatus = statusProp || 'processing';
    }
  });

  // Use local status as the source of truth (allows updates from embed events)
  let status = $derived(localStatus);

  // Stale-embed recovery: if still "processing" after STALE_CHECK_MS, send a
  // request_embed to the server. Redis pub/sub is fire-and-forget — if the
  // "finished" event was lost, this one-shot check recovers it.
  // A second check at STALE_CHECK_FINAL_MS acts as a final fallback for
  // genuinely slow skills.
  const STALE_CHECK_MS = 5_000;
  const STALE_CHECK_FINAL_MS = 15_000;
  let staleTimer1: ReturnType<typeof setTimeout> | null = null;
  let staleTimer2: ReturnType<typeof setTimeout> | null = null;
  
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
    
    
    // Update status immediately from event if provided
    if (newStatus && (newStatus === 'processing' || newStatus === 'finished' || newStatus === 'error' || newStatus === 'cancelled')) {
      localStatus = newStatus;
      // Mark store-resolved for terminal statuses so $effect won't revert on re-mount
      if (newStatus !== 'processing') {
        storeResolved = true;
      }
    }
    
    // CRITICAL: Do NOT refetch for error/cancelled embeds.
    // Error embeds are never persisted to IndexedDB, so refetchFromStore() would
    // call resolveEmbed() which would find nothing and re-request from server,
    // creating an infinite loop. The status update above is sufficient for the UI.
    if (newStatus === 'error' || newStatus === 'cancelled') {
      return;
    }
    
    // Refetch from store to get full data and notify child components
    refetchFromStore();
  }
  
  /**
   * Refetch embed data from the store
   * This ensures we have the latest data after an update
   * and notifies child components via onEmbedDataUpdated callback
   * 
   * NOTE: Uses resolveEmbed() which checks BOTH:
   * - Regular embedStore (for encrypted user embeds)
   * - communityDemoStore (for cleartext demo chat embeds)
   * 
   * This is critical for demo chats where embeds are stored separately
   * in the community demo store and wouldn't be found by embedStore.get().
   * 
   * NOTE: Skips fetch for "legacy-*" IDs which are synthetic IDs created by
   * transformLegacyResults() in search fullscreens. These IDs don't exist in
   * IndexedDB - the data is already available from the parent component's props.
   */
  async function refetchFromStore() {
    // Skip refetch for legacy IDs - these are synthetic IDs from legacy results
    // that don't exist in IndexedDB. The data is already available from props.
    if (id.startsWith('legacy-')) {
      return;
    }
    
    try {
      // Use resolveEmbed() which checks both regular embedStore AND communityDemoStore
      // This is essential for demo chats where embeds are stored in a separate store
      const embedData = await resolveEmbed(id);
      if (embedData) {
        
        // Update status from fetched data.
        // CRITICAL: Don't regress from a terminal status back to "processing".
        // The in-memory embedCache may still hold stale "processing" data from
        // setInMemoryOnly() (streaming row events) while the finalization path's
        // putEncrypted() hasn't completed yet. If handleEmbedUpdate already set
        // a terminal status (storeResolved=true), trust it over stale store data.
        if (embedData.status && (embedData.status === 'processing' || embedData.status === 'finished' || embedData.status === 'error' || embedData.status === 'cancelled')) {
          if (!storeResolved || embedData.status !== 'processing') {
            localStatus = embedData.status;
          }
          if (embedData.status !== 'processing') {
            storeResolved = true;
          }
        }

        // Decode content and notify child component if callback is provided.
        // Skip propagating stale "processing" data to child components when a
        // terminal status is already known — prevents overwriting correct state
        // in SheetEmbedPreview/CodeEmbedPreview etc.
        if (storeResolved && embedData.status === 'processing') {
          return;
        }
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
  let embedUpdateListener: ((event: Event) => void) | null = null;
  
  /**
   * Stale-embed recovery: if embed is still "processing" after a delay, re-request
   * from the server. This recovers from lost Redis pub/sub "finished" events.
   * One-shot check (not a polling loop) — a second timer acts as final fallback.
   */
  async function requestStaleEmbedUpdate() {
    // Only request if still processing and not a legacy/synthetic ID
    if (localStatus !== 'processing' || id.startsWith('legacy-')) return;

    try {
      const { webSocketService } = await import('../../services/websocketService');
      console.info(
        `[UnifiedEmbedPreview] Stale recovery: requesting embed ${id} from server (still processing after mount)`
      );
      await webSocketService.sendMessage('request_embed', { embed_id: id });
    } catch (err) {
      console.debug(`[UnifiedEmbedPreview] Stale recovery request failed for ${id}:`, err);
    }
  }

  onMount(() => {

    // Subscribe to embedUpdated events from chatSyncService
    embedUpdateListener = handleEmbedUpdate as (event: Event) => void;
    chatSyncService.addEventListener('embedUpdated', embedUpdateListener);

    // Do an initial fetch to ensure we have the latest data
    // (in case the embed was updated between render and mount)
    refetchFromStore();

    // Stale-embed recovery timers: if the embed is still "processing" after 5s/15s,
    // re-request from the server. Redis pub/sub is fire-and-forget — if the "finished"
    // event was lost (transient Redis issue, WebSocket reconnect), this recovers it.
    staleTimer1 = setTimeout(requestStaleEmbedUpdate, STALE_CHECK_MS);
    staleTimer2 = setTimeout(requestStaleEmbedUpdate, STALE_CHECK_FINAL_MS);

    // Enable scroll-driven pseudo tilt on coarse-pointer devices.
    viewportListenerCleanup = setupScrollTiltListeners();
  });
  
  onDestroy(() => {
    // Clean up stale-embed recovery timers
    if (staleTimer1) { clearTimeout(staleTimer1); staleTimer1 = null; }
    if (staleTimer2) { clearTimeout(staleTimer2); staleTimer2 = null; }

    // Clean up event listener
    if (embedUpdateListener) {
      chatSyncService.removeEventListener('embedUpdated', embedUpdateListener);
      embedUpdateListener = null;
    }

    if (viewportListenerCleanup) {
      viewportListenerCleanup();
      viewportListenerCleanup = null;
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
  let scrollTiltY = $state(0); // Normalized -1 to 1 from viewport center offset
  let isTouchTiltEnabled = $state(false);
  
  // Configuration for the tilt effect
  // NOTE: Keep values subtle for a polished feel without being distracting.
  // Large preview cards (.embed-preview-large-container ancestor) use even more
  // reduced tilt because the 3D effect is too pronounced on wider/taller cards.
  const TILT_MAX_ANGLE_STANDARD = 3;      // Standard card max tilt (degrees)
  const TILT_MAX_ANGLE_LARGE = 1;         // Large card max tilt (degrees)
  const TILT_PERSPECTIVE_STANDARD = 800;   // Standard perspective (px)
  const TILT_PERSPECTIVE_LARGE = 1200;     // Large perspective — more subtle (px)
  const TILT_SCALE_STANDARD = 0.985;       // Standard scale on hover
  const TILT_SCALE_LARGE = 0.995;          // Large scale — barely noticeable

  // Detect whether this card is inside a large preview context.
  // Checked once when previewElement is bound (not reactive to DOM changes).
  // Matches both production (.embed-preview-large-container in EmbedPreviewLarge.svelte)
  // and dev showcase (.large-container in the dev preview page) wrappers —
  // both set container-name: embed-preview and trigger the @container CSS query.
  let isLargeContext = $state(false);
  $effect(() => {
    if (previewElement) {
      isLargeContext = !!(
        previewElement.closest('.embed-preview-large-container') ||
        previewElement.closest('.large-container')
      );
    }
  });

  let TILT_MAX_ANGLE = $derived(isLargeContext ? TILT_MAX_ANGLE_LARGE : TILT_MAX_ANGLE_STANDARD);
  let TILT_PERSPECTIVE = $derived(isLargeContext ? TILT_PERSPECTIVE_LARGE : TILT_PERSPECTIVE_STANDARD);
  let TILT_SCALE = $derived(isLargeContext ? TILT_SCALE_LARGE : TILT_SCALE_STANDARD);
  let isScrollTilting = $derived(
    status === 'finished' &&
    !isHovering &&
    isTouchTiltEnabled &&
    Math.abs(scrollTiltY) > 0.01
  );
  
  /**
   * Calculate CSS transform string for the 3D tilt effect
   * - Fine pointer: hover tilt from mouse position (X + Y)
   * - Coarse pointer: pseudo tilt from scroll position (Y only)
   */
  let tiltTransform = $derived.by(() => {
    // Only apply tilt to finished embeds
    if (status !== 'finished') {
      return '';
    }

    if (isHovering) {
      const rotateY = mouseX * TILT_MAX_ANGLE;
      const rotateX = -mouseY * TILT_MAX_ANGLE;
      return `perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TILT_SCALE})`;
    }

    if (isTouchTiltEnabled) {
      const rotateX = -scrollTiltY * TILT_MAX_ANGLE;
      return `perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(0deg) scale(${TILT_SCALE})`;
    }

    return '';
  });

  let viewportListenerCleanup: (() => void) | null = null;
  let scrollTiltAnimationFrame: number | null = null;

  function updateScrollTiltFromViewport() {
    if (!previewElement || typeof window === 'undefined' || !isTouchTiltEnabled || status !== 'finished') {
      scrollTiltY = 0;
      return;
    }

    const rect = previewElement.getBoundingClientRect();
    const viewportHalfHeight = Math.max(window.innerHeight / 2, 1);
    const elementCenterY = rect.top + rect.height / 2;
    const viewportCenterY = viewportHalfHeight;
    const normalizedY = (elementCenterY - viewportCenterY) / viewportHalfHeight;
    scrollTiltY = Math.max(-1, Math.min(1, normalizedY));
  }

  function scheduleScrollTiltUpdate() {
    if (typeof window === 'undefined' || scrollTiltAnimationFrame !== null) {
      return;
    }

    scrollTiltAnimationFrame = window.requestAnimationFrame(() => {
      scrollTiltAnimationFrame = null;
      updateScrollTiltFromViewport();
    });
  }

  function setupScrollTiltListeners() {
    if (typeof window === 'undefined') {
      return () => {};
    }

    const coarsePointerQuery = window.matchMedia('(pointer: coarse)');
    const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const addQueryListener = (query: MediaQueryList, handler: () => void) => {
      if ('addEventListener' in query) {
        query.addEventListener('change', handler);
      } else {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- legacy API fallback for older browsers
        (query as any).addListener(handler);
      }
    };
    const removeQueryListener = (query: MediaQueryList, handler: () => void) => {
      if ('removeEventListener' in query) {
        query.removeEventListener('change', handler);
      } else {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- legacy API fallback for older browsers
        (query as any).removeListener(handler);
      }
    };

    const updateTiltAvailability = () => {
      isTouchTiltEnabled = coarsePointerQuery.matches && !reducedMotionQuery.matches;
      if (isTouchTiltEnabled) {
        scheduleScrollTiltUpdate();
      } else {
        scrollTiltY = 0;
      }
    };

    const handleViewportChange = () => {
      if (!isTouchTiltEnabled || status !== 'finished') {
        return;
      }
      scheduleScrollTiltUpdate();
    };

    window.addEventListener('scroll', handleViewportChange, { passive: true });
    window.addEventListener('resize', handleViewportChange, { passive: true });
    addQueryListener(coarsePointerQuery, updateTiltAvailability);
    addQueryListener(reducedMotionQuery, updateTiltAvailability);
    updateTiltAvailability();

    return () => {
      window.removeEventListener('scroll', handleViewportChange);
      window.removeEventListener('resize', handleViewportChange);
      removeQueryListener(coarsePointerQuery, updateTiltAvailability);
      removeQueryListener(reducedMotionQuery, updateTiltAvailability);

      if (scrollTiltAnimationFrame !== null) {
        window.cancelAnimationFrame(scrollTiltAnimationFrame);
        scrollTiltAnimationFrame = null;
      }

      scrollTiltY = 0;
      isTouchTiltEnabled = false;
    };
  }

  $effect(() => {
    if (status === 'finished' && isTouchTiltEnabled) {
      scheduleScrollTiltUpdate();
    }
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
  
  // Handle click to open fullscreen (finished or error - error enables debug view)
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
    
    
    // Stop event propagation to prevent the click from bubbling to ReadOnlyMessage
    // which would show the context menu instead of opening fullscreen
    // NOTE: We don't call preventDefault() here because it might interfere with the click
    e.stopPropagation();
    
    if ((status === 'finished' || status === 'error') && onFullscreen) {
      
      try {
        onFullscreen();
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
  // 
  // OPTIMISTIC UPDATE: Immediately set localStatus = 'cancelled' so the stop button
  // disappears and the spinner stops right away. The server will later confirm via
  // skill_execution_status → embed_update → embedUpdated, which writes 'cancelled'
  // again — harmless. Without this, the embed stays in "processing" state for the
  // duration of the full network round-trip (cancel_skill WS → Redis write → skill
  // executor checks flag → status event back to client), which can be 1–3+ seconds
  // if the skill is in the middle of an external HTTP call.
  function handleStop() {
    if (onStop) {
      onStop();
    }
    // Optimistically mark as cancelled regardless of whether the call succeeded —
    // if it failed, onStop() will have logged an error and the server won't confirm,
    // so the embed will remain visually cancelled but won't actually be. This is
    // acceptable: the user wanted to stop, and the worst case is a stale UI state
    // that would resolve on next reload. No silent data loss occurs.
    if (localStatus === 'processing') {
      localStatus = 'cancelled';
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
  class:clickable={status === 'finished' || status === 'error'}
  class:hovering={isHovering && status === 'finished'}
  class:scroll-tilting={isScrollTilting}
  class:error={status === 'error'}
  data-embed-id={id}
  data-app-id={appId}
  data-skill-id={skillId}
  data-status={status}
  style={[
    tiltTransform ? `transform: ${tiltTransform};` : '',
    (!useMobileLayout && customHeight) ? `height: ${customHeight}px; min-height: ${customHeight}px; max-height: ${customHeight}px;` : ''
  ].filter(Boolean).join(' ')}
  {...((status === 'finished' || status === 'error') ? {
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
          {@render details({ isMobile: true, isLarge: false })}
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
        {titleIcon}
        {actionButton}
      />
    </div>
  {:else}
    <!-- Desktop Layout: Horizontal card (300x200px) -->
    <div class="desktop-layout">
      <!-- Details content (skill-specific) at top - with defensive guard -->
      <div class="details-section" class:full-width-image={hasFullWidthImage}>
        {#if details}
          {@render details({ isMobile: false, isLarge: isLargeContext })}
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
        {titleIcon}
        {actionButton}
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
  }
  
  /* Clickable embeds act like a single button: children shouldn't capture pointer events. */
  .unified-embed-preview.clickable .desktop-layout,
  .unified-embed-preview.clickable .mobile-layout {
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
  
  /* Interactive state for clickable previews (finished + error) */
  .unified-embed-preview.clickable {
    /* Ensure clickable cursor is always shown */
    cursor: pointer !important;
  }
  
  /* Hovering state (controlled by JS for tilt effect) */
  .unified-embed-preview.finished.hovering,
  .unified-embed-preview.finished.scroll-tilting {
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
  
  /* Full-width image content: remove padding, extend into BasicInfosBar area, */
  /* clip the image to rounded card corners. -61px covers the full bar height   */
  /* so the image fills the container with no grey gap at the bottom.            */
  .desktop-layout .details-section.full-width-image {
    padding-right: 0;
    padding-left: 0;
    margin-bottom: -61px;
    border-radius: 30px;
    overflow: hidden;
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

  /* ===========================================
     Responsive Expanded Layout (Container Query)
     ===========================================
     When this card is inside a container named "embed-preview" (set by
     EmbedPreviewLarge.svelte) wider than 400px, the card expands to
     full-width × 400px with the BasicInfosBar constrained to 300px and
     protruding 15px below the card. This replaces the old separate
     UnifiedEmbedPreviewLarge component.
     =========================================== */

  @container embed-preview (min-width: 401px) {
    .unified-embed-preview.desktop {
      width: 100% !important;
      min-width: unset !important;
      max-width: unset !important;
      height: 400px !important;
      min-height: 400px !important;
      max-height: 400px !important;
      margin-top: 10px;
      margin-bottom: 30px;
      overflow: visible !important;
    }

    .desktop-layout {
      overflow: visible !important;
    }

    /* BasicInfosBar stays at ~300px width, centered, protruding below the card */
    .desktop-layout :global(.basic-infos-bar.desktop) {
      width: 300px;
      max-width: 300px;
      min-width: unset;
      margin-left: auto;
      margin-right: auto;
      flex-shrink: 0;
      transform: translateY(15px);
      /* Shadow on the protruding info bar for depth — consistent across all embed types */
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.08);
    }

    /* ── Website-specific expanded overrides ────────────────────────────────
       Description text: 30% width, 16 lines visible in the taller card.
       Preview image: fills remaining space at 400px height.
       These MUST live here (not in WebsiteEmbedPreview) because on share
       pages the appId may not resolve, so the fallback path renders directly
       and still needs correct expanded styling. */

    .desktop-layout :global(.website-description) {
      max-width: 30% !important;
      width: 30% !important;
      flex: 0 1 30% !important;
      min-width: 0 !important;
      overflow: hidden !important;
      -webkit-line-clamp: 16 !important;
      line-clamp: 16 !important;
      margin-left: 20px !important;
    }

    .desktop-layout :global(.website-content-row) {
      align-items: stretch;
      height: 100%;
    }

    .desktop-layout :global(.website-preview-image:not(.full-width)) {
      flex: 1 1 0 !important;
      min-width: 0 !important;
      height: 400px !important;
      max-height: none !important;
      transform: none !important;
      overflow: hidden !important;
      border-radius: 0 30px 30px 0 !important;
    }

    .desktop-layout :global(.website-preview-image:not(.full-width) img) {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center;
      display: block;
    }
  }
</style>
