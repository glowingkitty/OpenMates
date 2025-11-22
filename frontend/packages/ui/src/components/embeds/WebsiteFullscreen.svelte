<!--
  Website embed fullscreen view component.
  Shows detailed website information with preview, description, and metadata.
  
  According to web.md architecture:
  - Shows website title, description, and preview image
  - "Open in new tab" button
  - Full metadata display
-->

<script lang="ts">
  import { scale } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  
  let {
    websiteData,
    onClose
  }: {
    websiteData: {
      url: string;
      title?: string;
      description?: string;
      favicon?: string;
      image?: string;
      snippets?: string[];
      meta_url_favicon?: string;
      thumbnail_original?: string;
    };
    onClose: () => void;
  } = $props();
  
  // Handle opening website in new tab
  function handleOpenInNewTab() {
    if (websiteData.url) {
      window.open(websiteData.url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle smooth closing animation
  function handleClose() {
    const overlay = document.querySelector('.website-fullscreen-overlay') as HTMLElement;
    if (overlay) {
      overlay.style.transform = 'scale(0.5)';
      overlay.style.opacity = '0';
    }
    
    setTimeout(() => {
      onClose();
    }, 300);
  }
  
  // Get display values
  const displayTitle = $derived(websiteData.title || new URL(websiteData.url).hostname);
  const displayDescription = $derived(websiteData.description || '');
  const faviconUrl = $derived(
    websiteData.meta_url_favicon || 
    websiteData.favicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(websiteData.url)}`
  );
  const imageUrl = $derived(
    websiteData.thumbnail_original || 
    websiteData.image || 
    `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(websiteData.url)}`
  );
</script>

<div
  class="website-fullscreen-overlay"
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
        onclick={handleOpenInNewTab}
        aria-label="Open in new tab"
      ></button>
      <button
        class="action-button clickable-icon icon_fullscreen"
        onclick={handleClose}
        aria-label="Close"
      ></button>
    </div>
    
    <!-- Header with title and favicon -->
    <div class="header">
      <div class="title-row">
        {#if faviconUrl}
          <img src={faviconUrl} alt="" class="favicon" />
        {/if}
        <div class="title">{displayTitle}</div>
      </div>
      <div class="url">{new URL(websiteData.url).hostname}</div>
    </div>
    
    <!-- Main content area -->
    <div class="content-area">
      <!-- Preview image -->
      {#if imageUrl}
        <div class="preview-image-container">
          <img 
            src={imageUrl} 
            alt={displayTitle}
            class="preview-image"
            loading="lazy"
            onerror={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        </div>
      {/if}
      
      <!-- Description -->
      {#if displayDescription}
        <div class="description">
          {displayDescription}
        </div>
      {/if}
      
      <!-- Snippets -->
      {#if websiteData.snippets && websiteData.snippets.length > 0}
        <div class="snippets">
          <h3>Snippets</h3>
          {#each websiteData.snippets as snippet}
            <div class="snippet">{snippet}</div>
          {/each}
        </div>
      {/if}
      
      <!-- Open button -->
      <div class="action-section">
        <button class="open-button" onclick={handleOpenInNewTab}>
          Open in new tab
        </button>
      </div>
    </div>
    
    <!-- Bottom preview bar -->
    <div class="bottom-preview">
      <div class="icon_rounded web"></div>
      <div class="preview-title">{displayTitle}</div>
    </div>
  </div>
</div>

<style>
  .website-fullscreen-overlay {
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
  
  .title-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  
  .favicon {
    width: 24px;
    height: 24px;
    border-radius: 4px;
    flex-shrink: 0;
  }
  
  .title {
    font-size: 18px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.4;
    word-break: break-word;
  }
  
  .url {
    font-size: 14px;
    color: var(--color-font-secondary);
  }
  
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 8px;
    margin-right: -8px;
    scrollbar-width: thin;
    scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
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
  
  .preview-image-container {
    width: 100%;
    margin-bottom: 16px;
    border-radius: 12px;
    overflow: hidden;
    background-color: var(--color-grey-15);
  }
  
  .preview-image {
    width: 100%;
    height: auto;
    display: block;
    object-fit: cover;
  }
  
  .description {
    font-size: 16px;
    line-height: 1.6;
    color: var(--color-font-primary);
    margin-bottom: 16px;
  }
  
  .snippets {
    margin-bottom: 24px;
  }
  
  .snippets h3 {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-font-primary);
    margin-bottom: 12px;
  }
  
  .snippet {
    font-size: 14px;
    line-height: 1.5;
    color: var(--color-font-secondary);
    padding: 12px;
    background-color: var(--color-grey-15);
    border-radius: 8px;
    margin-bottom: 8px;
  }
  
  .action-section {
    margin-top: 24px;
    margin-bottom: 16px;
  }
  
  .open-button {
    width: 100%;
    padding: 12px 24px;
    background-color: var(--color-error);
    color: white;
    border: none;
    border-radius: 20px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
  }
  
  .open-button:hover {
    background-color: var(--color-error-dark);
    transform: translateY(-2px);
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

