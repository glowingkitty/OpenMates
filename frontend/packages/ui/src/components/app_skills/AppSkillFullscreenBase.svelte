<!--
  frontend/packages/ui/src/components/app_skills/AppSkillFullscreenBase.svelte
  
  Base component for all app skill fullscreen views.
  Provides common structure: close button, header, and content area.
  
  According to web.md architecture:
  - Fullscreen views show detailed results
  - Top bar has share/export and minimize buttons
  - Content area is scrollable
  - Bottom has preview element with title and icon
-->

<script lang="ts">
  import { scale } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { _ } from 'svelte-i18n';
  import type { BaseSkillPreviewData } from '../../types/appSkills';
  
  // Props using Svelte 5 runes
  // Using 'any' for previewData to allow subtypes (e.g., WebSearchSkillPreviewData extends BaseSkillPreviewData)
  // Snippets are typed as 'any' to avoid TypeScript issues with Svelte 5 snippet types
  let {
    previewData,
    title,
    onClose,
    onShare,
    headerExtra,
    content
  }: {
    previewData: BaseSkillPreviewData | any; // Allow subtypes
    title: string;
    onClose: () => void;
    onShare?: () => void;
    headerExtra?: any; // Snippet type
    content: any; // Snippet type with params
  } = $props();
  
  // Handle smooth closing animation
  function handleClose() {
    const overlay = document.querySelector('.app-skill-fullscreen-overlay') as HTMLElement;
    if (overlay) {
      overlay.style.transform = 'scale(0.5)';
      overlay.style.opacity = '0';
    }
    
    // Delay the actual close callback to allow animation to play
    setTimeout(() => {
      onClose();
    }, 300);
  }
  
  // Handle share/export (opens in external provider)
  function handleShare() {
    if (onShare) {
      onShare();
    } else {
      // Default share action
      console.debug('[AppSkillFullscreenBase] Share action');
    }
  }
  
  // Create button props with onclick handlers (using type assertion for Svelte 5 onclick syntax)
  // TypeScript doesn't recognize onclick as a valid HTML attribute, but it's valid in Svelte 5
  const shareButtonProps = {
    onclick: handleShare,
    'aria-label': 'Share'
  } as any;
  
  const closeButtonProps = {
    onclick: handleClose,
    'aria-label': $_('enter_message.exit_fullscreen.text', { default: 'Exit fullscreen' })
  } as any;
</script>

<div
  class="app-skill-fullscreen-overlay"
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
      <button
        class="action-button clickable-icon icon_share"
        {...shareButtonProps}
      ></button>
      <button
        class="action-button clickable-icon icon_fullscreen"
        {...closeButtonProps}
      ></button>
    </div>
    
    <!-- Header with title -->
    <div class="header">
      <div class="title">{title}</div>
      {@render headerExtra?.()}
    </div>
    
    <!-- Main content area -->
    <div class="content-area">
      {@render content({ previewData })}
    </div>
    
    <!-- Bottom preview bar -->
    <div class="bottom-preview">
      <div class="icon_rounded {previewData.app_id}"></div>
      <div class="preview-title">{title}</div>
    </div>
  </div>
</div>

<style>
  .app-skill-fullscreen-overlay {
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
  }
  
  .top-bar {
    position: absolute;
    top: 16px;
    right: 16px;
    display: flex;
    gap: 12px;
    z-index: 10;
  }
  
  .action-button {
    opacity: 0.5;
    transition: opacity 0.2s;
  }
  
  .action-button:hover {
    opacity: 1;
  }
  
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
  
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 8px;
    margin-right: -8px;
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
  
  .bottom-preview {
    position: absolute;
    bottom: 32px;
    left: 50%;
    transform: translateX(-50%);
    height: 60px;
    background-color: var(--color-grey-20);
    border-radius: 30px;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 16px 0 70px;
    min-width: 200px;
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
</style>

