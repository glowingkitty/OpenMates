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
-->

<script lang="ts">
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import BasicInfosBar from './BasicInfosBar.svelte';
  
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
    status: 'processing' | 'finished' | 'error';
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
    /** Custom status text (overrides default status text) */
    customStatusText?: string;
    /** Whether to show skill icon (only for app skills, not for individual embeds like code, website, video) */
    showSkillIcon?: boolean;
    /** Whether the details content contains a full-width image (removes padding, adds negative margin) */
    hasFullWidthImage?: boolean;
  }
  
  let {
    id,
    appId,
    skillId,
    skillIconName,
    status,
    skillName,
    taskId,
    isMobile = false,
    onFullscreen,
    onStop,
    details,
    showStatus = true,
    faviconUrl,
    customStatusText,
    showSkillIcon = true,
    hasFullWidthImage = false
  }: Props = $props();
  
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
  let isContextMenuHandled = $state(false);
  
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
    // Only handle single touch
    if (e.touches.length !== 1 || status !== 'finished') {
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
        
        // Mark that we're handling a context menu
        isContextMenuHandled = true;
        
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
    // If this was triggered after a context menu, don't handle it
    if (isContextMenuHandled) {
      isContextMenuHandled = false;
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
  
  /**
   * Handle right-click context menu
   * Allow the event to bubble up to ReadOnlyMessage for proper context menu handling
   * Only prevent default browser context menu
   */
  function handleContextMenu(e: MouseEvent) {
    // Only handle context menu for finished embeds
    if (status !== 'finished') {
      return; // Let default behavior for processing/error states
    }
    
    // Prevent default browser context menu
    e.preventDefault();
    
    // Mark that we're handling a context menu to prevent normal click from firing
    isContextMenuHandled = true;
    
    // Don't stop propagation - let it bubble up to ReadOnlyMessage
    // ReadOnlyMessage will handle showing the context menu
    console.debug('[UnifiedEmbedPreview] Context menu event (right-click) - allowing to bubble up');
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
  function handleStopClick(e: MouseEvent) {
    e.stopPropagation();
    if (onStop) {
      onStop();
    }
  }
  
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
  class:error={status === 'error'}
  data-embed-id={id}
  data-app-id={appId}
  data-skill-id={skillId}
  data-status={status}
  {...(status === 'finished' ? {
    role: 'button',
    tabindex: 0,
    onclick: handleClick,
    onkeydown: handleKeydown,
    oncontextmenu: handleContextMenu,
    ontouchstart: handleTouchStart,
    ontouchmove: handleTouchMove,
    ontouchend: handleTouchEnd
  } : {
    role: 'presentation'
  })}
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
    background-color: var(--color-grey-30);
    border-radius: 30px;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    transition: background-color 0.2s, transform 0.2s, box-shadow 0.2s;
    overflow: hidden;
    box-sizing: border-box;
    /* Ensure context menu events bubble from child elements */
    /* Child elements like images should not block context menu events */
  }
  
  /* Ensure child elements (like images) don't block context menu events */
  .unified-embed-preview * {
    /* Allow context menu events to bubble up to the parent */
    /* Images and other child elements should not prevent context menu */
    pointer-events: auto;
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
    cursor: pointer;
  }
  
  .unified-embed-preview.finished:hover {
    transform: scale(0.98);
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
  }
  
  .unified-embed-preview.finished:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
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
  .desktop-layout .details-section.full-width-image {
    padding-right: 0;
    padding-left: 0;
    margin-bottom: -35px;
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

