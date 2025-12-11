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
  
  // Handle click to open fullscreen (only when finished)
  // Store preview element position for transition animation
  // CRITICAL: Stop event propagation to prevent ReadOnlyMessage from showing context menu
  function handleClick(e: MouseEvent) {
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
    onkeydown: handleKeydown
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

