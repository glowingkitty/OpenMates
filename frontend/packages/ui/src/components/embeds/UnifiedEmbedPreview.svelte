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
    /** Snippet for details content (skill-specific) */
    details: import('svelte').Snippet<[{ isMobile: boolean }]>;
  }
  
  let {
    id,
    appId,
    skillId,
    status,
    skillName,
    taskId,
    isMobile = false,
    onFullscreen,
    onStop,
    details
  }: Props = $props();
  
  // Determine layout based on prop and window width
  let useMobileLayout = $derived(
    isMobile || (typeof window !== 'undefined' && window.innerWidth <= 500)
  );
  
  // Status text from translations
  let statusText = $derived(() => {
    if (status === 'processing') {
      return $text('embeds.processing.text') || 'Processing...';
    } else if (status === 'finished') {
      return $text('embeds.completed.text') || 'Completed';
    }
    return $text('embeds.error.text') || 'Error';
  });
  
  // Handle click to open fullscreen (only when finished)
  function handleClick() {
    if (status === 'finished' && onFullscreen) {
      onFullscreen();
    }
  }
  
  // Handle keyboard navigation
  function handleKeydown(e: KeyboardEvent) {
    if ((e.key === 'Enter' || e.key === ' ') && status === 'finished') {
      e.preventDefault();
      handleClick();
    }
  }
  
  // Handle stop button click - prevent event propagation
  function handleStopClick(e: MouseEvent) {
    e.stopPropagation();
    if (onStop) {
      onStop();
    }
  }
</script>

<div
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
  role={status === 'finished' ? 'button' : undefined}
  tabindex={status === 'finished' ? 0 : undefined}
  onclick={status === 'finished' ? handleClick : undefined}
  onkeydown={status === 'finished' ? handleKeydown : undefined}
>
  {#if useMobileLayout}
    <!-- Mobile Layout: Vertical card (150x290px) -->
    <div class="mobile-layout">
      <!-- Details content (skill-specific) -->
      <div class="details-section">
        {@render details({ isMobile: true })}
      </div>
      
      <!-- App icon container (full width, 44px height, gradient background) -->
      <div class="app-icon-container {appId}">
        <div class="icon_rounded {appId}"></div>
      </div>
      
      <!-- Skill icon (centered) -->
      <div class="skill-icon-container">
        <div class="icon_rounded {skillId}"></div>
      </div>
      
      <!-- Status text lines -->
      <div class="status-text-container">
        <span class="status-label">{skillName}</span>
        <span class="status-value">{statusText()}</span>
      </div>
      
      <!-- Stop button (only when processing) -->
      {#if status === 'processing'}
        <button 
          class="stop-button"
          onclick={handleStopClick}
          aria-label={$text('embeds.stop.text') || 'Stop'}
          title={$text('embeds.stop.text') || 'Stop'}
        >
          <span class="clickable-icon icon_stop_processing"></span>
        </button>
      {/if}
    </div>
  {:else}
    <!-- Desktop Layout: Horizontal card (300x200px) -->
    <div class="desktop-layout">
      <!-- Details content (skill-specific) at top -->
      <div class="details-section">
        {@render details({ isMobile: false })}
      </div>
      
      <!-- basic_infos bar (61px height, 30px rounded edges, grey-0 background) -->
      <div class="basic-infos-bar">
        <!-- App icon in gradient circle (61x61px container, 26x26px icon) -->
        <div class="app-icon-circle {appId}">
          <div class="icon_rounded {appId}"></div>
        </div>
        
        <!-- Skill icon (29x29px) -->
        <div class="skill-icon">
          <div class="icon_rounded {skillId}"></div>
        </div>
        
        <!-- Status text -->
        <div class="status-text">
          <span class="status-label">{skillName}</span>
          <span class="status-value">{statusText()}</span>
        </div>
        
        <!-- Stop button (only when processing) -->
        {#if status === 'processing'}
          <button 
            class="stop-button"
            onclick={handleStopClick}
            aria-label={$text('embeds.stop.text') || 'Stop'}
            title={$text('embeds.stop.text') || 'Stop'}
          >
            <span class="clickable-icon icon_stop_processing"></span>
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  /* ===========================================
     Unified Embed Preview - Base Container
     =========================================== */
  
  .unified-embed-preview {
    position: relative;
    background-color: var(--color-grey-20);
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
    background-color: var(--color-grey-15);
    transform: translateY(-2px);
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
    gap: 12px;
  }
  
  .desktop-layout .details-section {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  
  /* basic_infos bar: 61px height, 30px rounded edges, grey-0 background */
  .basic-infos-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-0);
    border-radius: 30px;
    padding: 0 8px 0 0;
    flex-shrink: 0;
  }
  
  /* App icon circle: 61x61px with gradient background, contains 26x26px icon */
  .app-icon-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* App-specific gradient backgrounds */
  .app-icon-circle.web {
    background: linear-gradient(135deg, #FF6B6B 0%, #FF8E53 100%);
  }
  
  .app-icon-circle.videos {
    background: linear-gradient(135deg, #FF5252 0%, #FF1744 100%);
  }
  
  .app-icon-circle.code {
    background: linear-gradient(135deg, #7C4DFF 0%, #536DFE 100%);
  }
  
  .app-icon-circle.docs {
    background: linear-gradient(135deg, #448AFF 0%, #2979FF 100%);
  }
  
  .app-icon-circle.sheets {
    background: linear-gradient(135deg, #00C853 0%, #69F0AE 100%);
  }
  
  /* Override the default icon_rounded positioning for flex layout */
  .app-icon-circle .icon_rounded {
    width: 26px;
    height: 26px;
    /* Reset absolute positioning from base icon_rounded */
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  /* Override ::after pseudo-element positioning for smaller icons */
  .app-icon-circle .icon_rounded::after {
    background-size: 16px 16px;
  }
  
  /* Make the icon white on gradient background - override the background from base styles */
  .app-icon-circle .icon_rounded.web,
  .app-icon-circle .icon_rounded.videos,
  .app-icon-circle .icon_rounded.code,
  .app-icon-circle .icon_rounded.docs,
  .app-icon-circle .icon_rounded.sheets {
    background: transparent !important;
  }
  
  /* Override the icon mask/filter for white icons on gradient backgrounds */
  .app-icon-circle .icon_rounded::after {
    filter: brightness(0) invert(1);
  }
  
  /* Skill icon: 29x29px */
  .skill-icon {
    width: 29px;
    height: 29px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .skill-icon .icon_rounded {
    width: 29px;
    height: 29px;
    border-radius: 50%;
    /* Reset absolute positioning from base icon_rounded */
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  .skill-icon .icon_rounded::after {
    background-size: 18px 18px;
  }
  
  /* Status text container */
  .status-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
    flex: 1;
    min-width: 0;
    gap: 2px;
  }
  
  .status-label {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
  }
  
  .status-value {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
  }
  
  /* Stop button */
  .stop-button {
    width: 40px;
    height: 40px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 50%;
    transition: background-color 0.2s;
  }
  
  .stop-button:hover {
    background-color: rgba(0, 0, 0, 0.05);
  }
  
  .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    /* Icon styling is handled by global icon styles */
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
  
  /* App icon container: full width, 44px height, gradient background */
  .mobile-layout .app-icon-container {
    width: 100%;
    height: 44px;
    border-radius: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* App-specific gradient backgrounds for mobile */
  .mobile-layout .app-icon-container.web {
    background: linear-gradient(135deg, #FF6B6B 0%, #FF8E53 100%);
  }
  
  .mobile-layout .app-icon-container.videos {
    background: linear-gradient(135deg, #FF5252 0%, #FF1744 100%);
  }
  
  .mobile-layout .app-icon-container.code {
    background: linear-gradient(135deg, #7C4DFF 0%, #536DFE 100%);
  }
  
  .mobile-layout .app-icon-container.docs {
    background: linear-gradient(135deg, #448AFF 0%, #2979FF 100%);
  }
  
  .mobile-layout .app-icon-container.sheets {
    background: linear-gradient(135deg, #00C853 0%, #69F0AE 100%);
  }
  
  .mobile-layout .app-icon-container .icon_rounded {
    width: 26px;
    height: 26px;
    /* Reset absolute positioning from base icon_rounded */
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  .mobile-layout .app-icon-container .icon_rounded::after {
    background-size: 16px 16px;
    filter: brightness(0) invert(1);
  }
  
  /* Override background for icons inside gradient container */
  .mobile-layout .app-icon-container .icon_rounded.web,
  .mobile-layout .app-icon-container .icon_rounded.videos,
  .mobile-layout .app-icon-container .icon_rounded.code,
  .mobile-layout .app-icon-container .icon_rounded.docs,
  .mobile-layout .app-icon-container .icon_rounded.sheets {
    background: transparent !important;
  }
  
  /* Skill icon container (centered) */
  .mobile-layout .skill-icon-container {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .mobile-layout .skill-icon-container .icon_rounded {
    width: 29px;
    height: 29px;
    border-radius: 50%;
    /* Reset absolute positioning from base icon_rounded */
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  .mobile-layout .skill-icon-container .icon_rounded::after {
    background-size: 18px 18px;
  }
  
  /* Status text container (centered) */
  .mobile-layout .status-text-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 2px;
    flex-shrink: 0;
  }
  
  .mobile-layout .status-text-container .status-label {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
  }
  
  .mobile-layout .status-text-container .status-value {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
  }
  
  /* Stop button in mobile (centered) */
  .mobile-layout .stop-button {
    width: 40px;
    height: 40px;
    margin-top: auto;
  }
</style>

