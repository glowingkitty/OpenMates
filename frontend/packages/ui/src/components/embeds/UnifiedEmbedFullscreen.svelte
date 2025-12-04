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
    /** Optional copy handler (for copy button) */
    onCopy?: () => void;
    /** Optional share handler */
    onShare?: () => void;
    /** Snippet for header extra content (optional) */
    headerExtra?: import('svelte').Snippet<[]>;
    /** Snippet for main content - REQUIRED but made optional for defensive programming */
    content?: import('svelte').Snippet<[]>;
    /** Snippet for bottom bar (optional, defaults to basic infos bar) */
    bottomBar?: import('svelte').Snippet<[]>;
  }
  
  let {
    appId,
    skillId,
    title,
    onClose,
    onOpen,
    onCopy,
    onShare,
    headerExtra,
    content,
    bottomBar
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
  
  // Handle share/export action
  function handleShare() {
    if (onShare) {
      onShare();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Share action (no handler provided)');
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
      <!-- Left side: Open and Copy buttons -->
      <div class="top-bar-left">
        {#if onOpen}
          <button
            class="action-button open-button"
            onclick={onOpen}
            aria-label="Open"
            title="Open"
          >
            <span class="clickable-icon icon_share"></span>
          </button>
        {/if}
        {#if onCopy}
          <button
            class="action-button copy-button"
            onclick={onCopy}
            aria-label="Copy"
            title="Copy"
          >
            <span class="clickable-icon icon_copy"></span>
          </button>
        {/if}
      </div>
      
      <!-- Right side: Minimize button -->
      <div class="top-bar-right">
        <button
          class="action-button minimize-button clickable-icon icon_minimize"
          onclick={handleClose}
          aria-label="Minimize"
          title="Minimize"
        ></button>
      </div>
    </div>
    
    <!-- Header with title and optional extra content -->
    <div class="header">
      <div class="title">{title}</div>
      {#if headerExtra}
        {@render headerExtra()}
      {/if}
    </div>
    
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
    
    <!-- Bottom preview bar -->
    {#if bottomBar}
      {@render bottomBar()}
    {:else}
      <!-- Default bottom preview bar with app icon and title -->
      <div class="bottom-preview">
        <div class="icon_rounded {appId}"></div>
        <div class="preview-title">{title}</div>
      </div>
    {/if}
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
    padding: 16px;
    padding-top: 60px; /* Space for top bar */
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
  
  .action-button {
    width: 40px;
    height: 40px;
    opacity: 0.7;
    transition: opacity 0.2s, background-color 0.2s;
    background-color: rgba(0, 0, 0, 0.3);
    border: none;
    border-radius: 8px;
    cursor: pointer;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .action-button:hover {
    opacity: 1;
    background-color: rgba(0, 0, 0, 0.5);
  }
  
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
  
  /* Main content area (scrollable) - with padding for bottom bar */
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 8px;
    margin-right: -8px;
    padding-bottom: 80px; /* Space for bottom bar */
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
  
  /* Bottom preview bar - positioned absolute at bottom */
  .bottom-preview {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    height: 61px;
    min-height: 61px;
    max-width: 400px;
    width: calc(100% - 32px);
    background-color: var(--color-grey-20);
    border-radius: 30px;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 16px 0 70px;
    z-index: 3;
  }
  
  .preview-title {
    font-size: 16px;
    color: var(--color-font-primary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 300px;
  }
  
  /* Bottom bar wrapper for custom bottom bars (like BasicInfosBar) */
  /* Centered with gradient fade above - positioned within fullscreen overlay */
  :global(.bottom-bar-wrapper) {
    position: absolute;
    bottom: 5px;
    left: 0;
    right: 0;
    z-index: 3;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0 16px;
  }
  
  /* Gradient fade above the bar - creates smooth transition */
  :global(.bottom-bar-wrapper::before) {
    content: '';
    position: absolute;
    bottom: calc(100% - 16px); /* Overlap slightly with bottom bar */
    left: 0;
    right: 0;
    height: 100px;
    background: linear-gradient(
      to bottom,
      transparent 0%,
      var(--color-grey-20) 100%
    );
    pointer-events: none;
  }
  
  /* The actual bar inside the wrapper */
  :global(.bottom-bar-wrapper > *) {
    max-width: 400px;
    width: 100%;
    position: relative;
    z-index: 1;
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


