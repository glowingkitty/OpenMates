<!--
  frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
  
  Unified base component for all embed fullscreen views (app skills, websites, etc.)
  
  Structure:
  - Top bar with action buttons (share, close)
  - Header section with title and optional extra content via snippet
  - Main content area (scrollable) with skill-specific content via snippet
  - Bottom preview bar with app icon and title
  
  Similar to UnifiedEmbedPreview but for fullscreen views.
-->

<script lang="ts">
  import { scale } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { onMount, onDestroy } from 'svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import BasicInfosBar from './BasicInfosBar.svelte';
  
  /**
   * Props interface for unified embed fullscreen
   */
  interface Props {
    /** App identifier (e.g., 'web', 'videos', 'code') - used for icon display */
    appId: string;
    /** Skill identifier (e.g., 'search', 'get_transcript') */
    skillId?: string;
    /** Fullscreen title */
    title: string;
    /** Close handler */
    onClose: () => void;
    /** Optional open handler (for top-left open button) */
    onOpen?: () => void;
    /** Optional copy handler (for copy button) - copies text version of embed */
    onCopy?: () => void;
    /** Optional download handler (for download button) - downloads the embed */
    onDownload?: () => void;
    /** Optional share handler - opens share menu for the embed */
    onShare?: () => void;
    /** Snippet for header extra content (optional) */
    headerExtra?: import('svelte').Snippet<[]>;
    /** Snippet for main content - REQUIRED but made optional for defensive programming */
    content?: import('svelte').Snippet<[]>;
    /** Snippet for bottom bar (optional, defaults to basic infos bar) */
    bottomBar?: import('svelte').Snippet<[]>;
    /** BasicInfosBar props - used when bottomBar snippet is not provided */
    /** Skill icon name for BasicInfosBar */
    skillIconName?: string;
    /** Processing status for BasicInfosBar */
    status?: 'processing' | 'finished' | 'error';
    /** Skill display name for BasicInfosBar */
    skillName?: string;
    /** Task ID for BasicInfosBar */
    taskId?: string;
    /** Click handler for BasicInfosBar */
    onBasicInfosBarClick?: () => void;
    /** Custom favicon URL for BasicInfosBar */
    faviconUrl?: string;
    /** Whether to show skill icon in BasicInfosBar */
    showSkillIcon?: boolean;
    /** Custom status text for BasicInfosBar */
    customStatusText?: string;
  }
  
  let {
    appId,
    skillId,
    title,
    onClose,
    onOpen,
    onCopy,
    onDownload,
    onShare,
    headerExtra,
    content,
    bottomBar,
    skillIconName = '',
    status = 'finished',
    skillName,
    taskId,
    onBasicInfosBarClick,
    faviconUrl,
    showSkillIcon = true,
    customStatusText
  }: Props = $props();
  
  // DEBUG: Log when content snippet is missing - this helps identify which embed is broken
  $effect(() => {
    if (!content) {
      console.error('[UnifiedEmbedFullscreen] MISSING content snippet! This will cause rendering issues.', {
        appId,
        skillId,
        title
      });
    }
  });
  
  // Handle smooth closing animation
  function handleClose() {
    const overlay = document.querySelector('.unified-embed-fullscreen-overlay') as HTMLElement;
    if (overlay) {
      overlay.style.transform = 'scale(0.5)';
      overlay.style.opacity = '0';
    }
    
    // Delay the actual close callback to allow animation to play
    setTimeout(() => {
      onClose();
    }, 300);
  }
  
  // Handle share action - opens share menu for the embed
  function handleShare() {
    if (onShare) {
      onShare();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Share action (no handler provided)');
    }
  }
  
  // Handle copy action - copies text version of embed to clipboard
  function handleCopy() {
    if (onCopy) {
      onCopy();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Copy action (no handler provided)');
    }
  }
  
  // Handle download action - downloads the embed
  function handleDownload() {
    if (onDownload) {
      onDownload();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Download action (no handler provided)');
    }
  }
  
  // Close fullscreen when user switches to a different chat
  function handleChatSelected() {
    console.debug('[UnifiedEmbedFullscreen] Chat selected, closing fullscreen');
    onClose(); // Close immediately without animation for smoother UX
  }
  
  onMount(() => {
    // Listen for chat selection events to close fullscreen
    window.addEventListener('globalChatSelected', handleChatSelected);
  });
  
  onDestroy(() => {
    window.removeEventListener('globalChatSelected', handleChatSelected);
  });
</script>

<div
  class="unified-embed-fullscreen-overlay"
  in:scale={{
    duration: 300,
    delay: 0,
    opacity: 0.5,
    start: 0.5,
    easing: cubicOut
  }}
>
  <div class="fullscreen-container">
    <!-- Top bar with action buttons -->
    <div class="top-bar">
      <!-- Left side: Share, Copy, and Download buttons -->
      <div class="top-bar-left">
        <!-- Share button - always shown -->
        <div class="button-wrapper">
          <button
            class="action-button share-button"
            onclick={handleShare}
            aria-label={$text('chat.share.text') || 'Share'}
            title={$text('chat.share.text') || 'Share'}
          >
            <span class="clickable-icon icon_share"></span>
          </button>
        </div>
        <!-- Copy button -->
        {#if onCopy}
          <div class="button-wrapper">
            <button
              class="action-button copy-button"
              onclick={handleCopy}
              aria-label="Copy"
              title="Copy"
            >
              <span class="clickable-icon icon_copy"></span>
            </button>
          </div>
        {/if}
        <!-- Download button -->
        {#if onDownload}
          <div class="button-wrapper">
            <button
              class="action-button download-button"
              onclick={handleDownload}
              aria-label="Download"
              title="Download"
            >
              <span class="clickable-icon icon_download"></span>
            </button>
          </div>
        {/if}
      </div>
      
      <!-- Right side: Minimize button -->
      <div class="top-bar-right">
        <div class="button-wrapper">
          <button
            class="action-button minimize-button"
            onclick={handleClose}
            aria-label="Minimize"
            title="Minimize"
          >
            <span class="clickable-icon icon_minimize"></span>
          </button>
        </div>
      </div>
    </div>
    
    <!-- Header with title and optional extra content (only show if title is provided and not empty) -->
    {#if title?.trim() && headerExtra}
      <div class="header">
        <div class="title">{title}</div>
        {@render headerExtra()}
      </div>
    {:else if title?.trim()}
      <div class="header">
        <div class="title">{title}</div>
      </div>
    {/if}
    
    <!-- Main content area (scrollable) - with defensive guard -->
    <div class="content-area">
      {#if content}
        {@render content()}
      {:else}
        <!-- Fallback when content snippet is missing -->
        <div class="missing-content-fallback">
          <p>Content unavailable</p>
        </div>
      {/if}
    </div>
    
    <!-- Bottom gradient and BasicInfosBar -->
    <div class="bottom-gradient-wrapper">
      <!-- Gradient fade from transparent to grey-0 -->
      <div class="bottom-gradient"></div>
      
      <!-- Bottom bar (BasicInfosBar or custom) -->
      <div class="bottom-bar-container">
        {#if bottomBar}
          {@render bottomBar()}
        {:else if skillName && skillId}
          <!-- Default BasicInfosBar with same content as embed preview -->
          {#if onBasicInfosBarClick}
            <button 
              class="basic-infos-bar-wrapper clickable"
              onclick={onBasicInfosBarClick}
              type="button"
            >
              <BasicInfosBar
                {appId}
                {skillId}
                skillIconName={skillIconName || skillId}
                {status}
                {skillName}
                {taskId}
                {faviconUrl}
                {showSkillIcon}
                {customStatusText}
              />
            </button>
          {:else}
            <div class="basic-infos-bar-wrapper">
              <BasicInfosBar
                {appId}
                {skillId}
                skillIconName={skillIconName || skillId}
                {status}
                {skillName}
                {taskId}
                {faviconUrl}
                {showSkillIcon}
                {customStatusText}
              />
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  /* ===========================================
     Unified Embed Fullscreen - Base Container
     =========================================== */
  
  .unified-embed-fullscreen-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: var(--color-grey-20);
    border-radius: 17px;
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    z-index: 100;
    display: flex;
    flex-direction: column;
    transform-origin: center center;
    transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1),
                opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
    overflow: hidden;
  }
  
  .fullscreen-container {
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
  }
  
  /* Top bar with action buttons - ABSOLUTE position within fullscreen overlay */
  .top-bar {
    position: absolute;
    top: 16px;
    left: 16px;
    right: 16px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    z-index: 10;
    pointer-events: none;
  }
  
  .top-bar-left {
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: auto;
  }
  
  .top-bar-right {
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: auto;
  }
  
  /* Button wrapper - matches new-chat-button-wrapper design from ActiveChat.svelte */
  .button-wrapper {
    background-color: var(--color-grey-10);
    border-radius: 40px;
    padding: 5.5px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .action-button {
    width: 40px;
    height: 40px;
    min-width: 40px;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    transition: background-color 0.2s;
  }
  
  .action-button:hover {
    background-color: rgba(0, 0, 0, 0.05);
  }
  
  /* Icon styling inside action buttons */
  .action-button .clickable-icon {
    width: 24px;
    height: 24px;
  }
  
  /* Header section */
  .header {
    margin-top: 16px;
    margin-bottom: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .title {
    font-size: 18px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.4;
    word-break: break-word;
  }
  
  /* Main content area (scrollable) - scrollable behind the fixed top and bottom bars */
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 8px;
    margin-right: -8px;
    padding-bottom: 120px; /* Space for absolute positioned bottom bar and gradient */
    scrollbar-width: thin;
    scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
    transition: scrollbar-color 0.2s ease;
  }
  
  .content-area:hover {
    scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
  }
  
  .content-area::-webkit-scrollbar {
    width: 8px;
  }
  
  .content-area::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .content-area::-webkit-scrollbar-thumb {
    background-color: rgba(128, 128, 128, 0.2);
    border-radius: 4px;
    border: 2px solid transparent;
    transition: background-color 0.2s ease;
  }
  
  .content-area:hover::-webkit-scrollbar-thumb {
    background-color: rgba(128, 128, 128, 0.5);
  }
  
  .content-area::-webkit-scrollbar-thumb:hover {
    background-color: rgba(128, 128, 128, 0.7);
  }
  
  /* Bottom gradient and bar wrapper - ABSOLUTE positioned at bottom */
  .bottom-gradient-wrapper {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 3;
    pointer-events: none;
  }
  
  /* Gradient fade from transparent (0%) to grey-20 (100% opacity) - matches fullscreen background */
  .bottom-gradient {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 120px;
    background: linear-gradient(
      to bottom,
      transparent 0%,
      var(--color-grey-20) 100%
    );
    pointer-events: none;
  }
  
  /* Bottom bar container - centered, positioned at absolute bottom */
  .bottom-bar-container {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px;
    pointer-events: auto;
  }
  
  /* BasicInfosBar wrapper - max-width 300px as required */
  .basic-infos-bar-wrapper {
    max-width: 300px;
    width: 100%;
    border: none;
    background: transparent;
    padding: 0;
    cursor: default;
  }
  
  /* Ensure BasicInfosBar inside wrapper respects max-width */
  .basic-infos-bar-wrapper :global(.basic-infos-bar) {
    max-width: 300px;
  }
  
  .basic-infos-bar-wrapper.clickable {
    cursor: pointer;
    transition: opacity 0.2s;
  }
  
  .basic-infos-bar-wrapper.clickable:hover {
    opacity: 0.9;
  }
  
  /* ===========================================
     Fallback for Missing Content Snippet
     =========================================== */
  
  .missing-content-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-grey-70);
    font-size: 16px;
    text-align: center;
  }
</style>


