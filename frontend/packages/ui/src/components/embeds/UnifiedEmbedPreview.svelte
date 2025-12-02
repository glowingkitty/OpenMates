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
    /** Snippet for details content (skill-specific) */
    details: import('svelte').Snippet<[{ isMobile: boolean }]>;
    /** Whether to show status line in basic infos bar (default: true) */
    showStatus?: boolean;
    /** Custom favicon URL for basic infos bar (shows instead of app icon) */
    faviconUrl?: string;
    /** Custom status text (overrides default status text) */
    customStatusText?: string;
    /** Whether to show skill icon (only for app skills, not for individual embeds like code, website, video) */
    showSkillIcon?: boolean;
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
    showSkillIcon = true
  }: Props = $props();
  
  // Determine layout based on isMobile prop only
  // Mobile layout should only be used inside groups of embedded previews
  // when the surrounding container width gets too small (set by parent component)
  // Otherwise, desktop layout is used by default
  let useMobileLayout = $derived(isMobile);
  
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
  
  // Wrapper for BasicInfosBar onStop prop (it expects () => void)
  function handleStop() {
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
      <!-- Details content (skill-specific) at top -->
      <div class="details-section">
        {@render details({ isMobile: false })}
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
    padding-right: 20px;
    padding-left: 20px;
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
</style>

