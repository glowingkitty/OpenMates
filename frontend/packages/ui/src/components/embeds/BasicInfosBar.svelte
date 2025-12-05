<!--
  frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
  
  Reusable basic info bar component used in both embed previews and fullscreen views.
  
  Structure:
  - App icon in gradient circle (61x61px container, 26x26px icon)
    OR custom favicon (when faviconUrl is provided)
  - Skill icon (29x29px)
  - Status text (skill name/title + optional processing status)
  - Stop button (when processing)
  
  Supports both desktop and mobile layouts.
-->

<script lang="ts">
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * Props interface for basic info bar
   */
  interface Props {
    /** App identifier (e.g., 'web', 'videos', 'code') - used for gradient color */
    appId: string;
    /** Skill identifier (e.g., 'search', 'get_transcript') */
    skillId: string;
    /** Icon name for the skill icon (e.g., 'search', 'videos', 'book') */
    skillIconName: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Skill display name (shown in status text) */
    skillName: string;
    /** Optional task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for stop button */
    onStop?: () => void;
    /** Whether to show the status text line (default: true) */
    showStatus?: boolean;
    /** Custom favicon URL to show instead of app icon */
    faviconUrl?: string;
    /** Whether to show skill icon (only for app skills, not for individual embeds like code, website, video) */
    showSkillIcon?: boolean;
    /** Custom status text (overrides default status text) */
    customStatusText?: string;
  }
  
  let {
    appId,
    skillId,
    skillIconName,
    status,
    skillName,
    taskId,
    isMobile = false,
    onStop,
    showStatus = true,
    faviconUrl,
    showSkillIcon = true,
    customStatusText
  }: Props = $props();
  
  // Status text from translations or custom text
  let statusText = $derived(() => {
    // Use custom status text if provided
    if (customStatusText) {
      return customStatusText;
    }
    
    // Otherwise use default status text
    if (status === 'processing') {
      return $text('embeds.processing.text');
    } else if (status === 'finished') {
      return $text('embeds.completed.text');
    }
    return $text('embeds.error.text');
  });
  
  // Compute app gradient style using CSS variables from theme.css
  let appGradientStyle = $derived(`background: var(--color-app-${appId});`);
  
  // Handle stop button click - prevent event propagation
  function handleStopClick(e: MouseEvent) {
    e.stopPropagation();
    if (onStop) {
      onStop();
    }
  }
</script>

{#if isMobile}
  <!-- Mobile Layout: Vertical layout with app icon, skill icon, status text, and stop button -->
  <div class="basic-infos-bar mobile">
    <!-- App icon container OR favicon (full width, 44px height, gradient background) -->
    {#if faviconUrl}
      <div class="app-icon-container {appId}" style={appGradientStyle}>
        <img src={faviconUrl} alt="" class="favicon-image-mobile" />
      </div>
    {:else}
      <div class="app-icon-container {appId}" style={appGradientStyle}>
        <div class="icon_rounded {appId}"></div>
      </div>
    {/if}
    
    <!-- Skill icon (centered) - only show for app skills -->
    {#if showSkillIcon}
      <div class="skill-icon-container">
        <div class="skill-icon" data-skill-icon={skillIconName}></div>
      </div>
    {/if}
    
    <!-- Status text lines -->
    <div class="status-text-container" class:single-line={!showStatus}>
      <span class="status-label">{skillName}</span>
      {#if showStatus}
        <span class="status-value">{statusText()}</span>
      {/if}
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
  <!-- Desktop Layout: Horizontal bar (61px height, 30px rounded edges, grey-20 background) -->
  <div class="basic-infos-bar desktop">
    <!-- App icon in gradient circle (always show app icon, not favicon) -->
    <div class="app-icon-circle {appId}" style={appGradientStyle}>
      <div class="icon_rounded {appId}"></div>
    </div>
    
    <!-- Skill icon (29x29px) - only show for app skills -->
    {#if showSkillIcon}
      <div class="skill-icon" data-skill-icon={skillIconName}></div>
    {/if}
    
    <!-- Status text with optional favicon next to title -->
    <div class="status-text" class:single-line={!showStatus}>
      <span class="status-label">
        {#if faviconUrl}
          <img src={faviconUrl} alt="" class="title-favicon" onerror={(e) => {
            (e.target as HTMLImageElement).style.display = 'none';
          }} />
        {/if}
        <span class="title-text">{skillName}</span>
      </span>
      {#if showStatus}
        <span class="status-value">{statusText()}</span>
      {/if}
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
{/if}

<style>
  /* ===========================================
     Basic Infos Bar - Desktop Layout
     =========================================== */
  
  .basic-infos-bar.desktop {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-30);
    border-radius: 30px;
    padding: 0 0 0 0;
    flex-shrink: 0;
    z-index: 1;
  }
  
  /* App icon circle: 61x61px with gradient background, contains 26x26px icon */
  /* Gradient is dynamically set via inline style using CSS variables from theme.css */
  .basic-infos-bar.desktop .app-icon-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* Override the default icon_rounded positioning for flex layout */
  .basic-infos-bar.desktop .app-icon-circle .icon_rounded {
    width: 26px;
    height: 26px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  /* Make the icon white on gradient background */
  .basic-infos-bar.desktop .app-icon-circle .icon_rounded {
    background: transparent !important;
  }
  
  .basic-infos-bar.desktop .app-icon-circle .icon_rounded::after {
    filter: brightness(0) invert(1);
  }
  
  /* Skill icon: 29x29px with color-grey-70, dynamically set icon via data attribute */
  .basic-infos-bar.desktop .skill-icon {
    width: 29px;
    height: 29px;
    background-color: var(--color-grey-70);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
    flex-shrink: 0;
  }
  
  /* Status text container */
  .basic-infos-bar.desktop .status-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
    flex: 1;
    min-width: 0;
    gap: 2px;
  }
  
  .basic-infos-bar.desktop .status-label {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
    display: flex;
    align-items: center;
    gap: 8px;
    overflow: hidden;
  }
  
  .basic-infos-bar.desktop .title-favicon {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    flex-shrink: 0;
    object-fit: cover;
  }
  
  .basic-infos-bar.desktop .title-text {
    flex: 1;
    min-width: 0;
    /* Limit to 2 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .basic-infos-bar.desktop .status-value {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
  }
  
  /* Single line mode: center the label vertically */
  .basic-infos-bar.desktop .status-text.single-line {
    justify-content: center;
  }
  
  .basic-infos-bar.desktop .status-text.single-line .status-label {
    font-size: 16px;
    line-height: 1.4;
  }
  
  /* Stop button - aligned to the right with no extra spacing */
  /* Override global button styles from buttons.css */
  .basic-infos-bar.desktop .stop-button {
    width: 40px;
    height: 40px;
    background: none !important;
    background-color: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin-left: auto !important;
    margin-right: 10px !important;
    min-width: auto !important;
    filter: none !important;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 50%;
    transition: background-color 0.2s;
  }
  
  .basic-infos-bar.desktop .stop-button:hover {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 1.02 from buttons.css */
  }
  
  .basic-infos-bar.desktop .stop-button:active {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 0.98 from buttons.css */
    filter: none !important;
  }
  
  /* Stop button icon - red color matching MessageInput stop button */
  .basic-infos-bar.desktop .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    background: red !important;
    transition: background 0.2s ease;
    /* Ensure mask-image is properly applied */
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
  }
  
  .basic-infos-bar.desktop .stop-button:hover .clickable-icon.icon_stop_processing {
    background: darkred !important;
  }
  
  /* ===========================================
     Basic Infos Bar - Mobile Layout
     =========================================== */
  
  .basic-infos-bar.mobile {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 13px;
  }
  
  /* App icon container: full width, 44px height, gradient background */
  .basic-infos-bar.mobile .app-icon-container {
    width: 100%;
    height: 44px;
    border-radius: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .basic-infos-bar.mobile .app-icon-container .icon_rounded {
    width: 26px;
    height: 26px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  .basic-infos-bar.mobile .app-icon-container .icon_rounded::after {
    background-size: 16px 16px;
    filter: brightness(0) invert(1);
  }
  
  .basic-infos-bar.mobile .app-icon-container .icon_rounded {
    background: transparent !important;
  }
  
  /* Mobile favicon image */
  .basic-infos-bar.mobile .favicon-image-mobile {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    object-fit: cover;
  }
  
  /* Skill icon container (centered) */
  .basic-infos-bar.mobile .skill-icon-container {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .basic-infos-bar.mobile .skill-icon-container .skill-icon {
    width: 29px;
    height: 29px;
    background-color: var(--color-grey-70);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }
  
  /* Status text container (centered) */
  .basic-infos-bar.mobile .status-text-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 2px;
    flex-shrink: 0;
  }
  
  .basic-infos-bar.mobile .status-text-container .status-label {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
  }
  
  .basic-infos-bar.mobile .status-text-container .status-value {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
  }
  
  /* Single line mode for mobile */
  .basic-infos-bar.mobile .status-text-container.single-line {
    justify-content: center;
  }
  
  .basic-infos-bar.mobile .status-text-container.single-line .status-label {
    font-size: 14px;
    line-height: 1.4;
  }
  
  /* Stop button in mobile (centered) */
  /* Override global button styles from buttons.css */
  .basic-infos-bar.mobile .stop-button {
    width: 40px;
    height: 40px;
    margin-top: auto;
    margin-right: 0 !important; /* Override margin-right: 10px from buttons.css */
    background: none !important;
    background-color: transparent !important;
    border: none !important;
    padding: 0 !important;
    min-width: auto !important;
    filter: none !important;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    transition: background-color 0.2s;
  }
  
  .basic-infos-bar.mobile .stop-button:hover {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 1.02 from buttons.css */
  }
  
  .basic-infos-bar.mobile .stop-button:active {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 0.98 from buttons.css */
    filter: none !important;
  }
  
  /* Stop button icon - red color matching MessageInput stop button */
  .basic-infos-bar.mobile .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    background: red !important;
    transition: background 0.2s ease;
    /* Ensure mask-image is properly applied */
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
  }
  
  .basic-infos-bar.mobile .stop-button:hover .clickable-icon.icon_stop_processing {
    background: darkred !important;
  }
</style>

