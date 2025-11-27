<!--
  frontend/packages/ui/src/components/embeds/WebsiteCard.svelte
  
  Simple website card for use in fullscreen grids (e.g., search results).
  Shows:
  - Top: Favicon (20x20px) + Title (16px, truncated)
  - Content: Description (left) + Image (right, if available)
  
  This is a lightweight version without the BasicInfosBar,
  designed for displaying multiple website results in a grid.
-->

<script lang="ts">
  /**
   * Props for website card
   */
  interface Props {
    /** Website URL */
    url: string;
    /** Website title */
    title?: string;
    /** Website description/snippet */
    description?: string;
    /** Favicon URL */
    favicon?: string;
    /** Preview image URL */
    image?: string;
    /** Click handler to open website */
    onClick?: () => void;
  }
  
  let {
    url,
    title,
    description,
    favicon,
    image,
    onClick
  }: Props = $props();
  
  // Get display values with fallbacks
  let displayTitle = $derived(title || getHostname(url));
  let faviconUrl = $derived(
    favicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(url)}`
  );
  let imageUrl = $derived(image);
  
  // Extract hostname from URL safely
  function getHostname(urlStr: string): string {
    try {
      return new URL(urlStr).hostname;
    } catch {
      return urlStr;
    }
  }
  
  // Handle click on the card
  function handleClick() {
    if (onClick) {
      onClick();
    } else {
      // Default: open URL in new tab
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle keyboard navigation
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleClick();
    }
  }
  
  // Track image load state for error handling
  let imageError = $state(false);
</script>

<div
  class="website-card"
  role="button"
  tabindex="0"
  onclick={handleClick}
  onkeydown={handleKeydown}
>
  <!-- Header: Favicon + Title -->
  <div class="card-header">
    <img 
      src={faviconUrl} 
      alt="" 
      class="favicon"
      onerror={(e) => {
        (e.target as HTMLImageElement).style.display = 'none';
      }}
    />
    <span class="title">{displayTitle}</span>
  </div>
  
  <!-- Content: Description (left) + Image (right) -->
  <div class="card-content">
    {#if description}
      <p class="description">{description}</p>
    {/if}
    
    {#if imageUrl && !imageError}
      <div class="preview-image">
        <img 
          src={imageUrl} 
          alt={displayTitle}
          loading="lazy"
          onerror={() => {
            imageError = true;
          }}
        />
      </div>
    {/if}
  </div>
</div>

<style>
  /* ===========================================
     Website Card - Simple card for fullscreen grids
     =========================================== */
  
  .website-card {
    display: flex;
    flex-direction: column;
    background-color: var(--color-grey-30);
    border-radius: 16px;
    padding: 16px;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
    height: 180px;
    box-sizing: border-box;
    overflow: hidden;
  }
  
  .website-card:hover {
    transform: scale(0.98);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  
  .website-card:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* ===========================================
     Card Header: Favicon + Title
     =========================================== */
  
  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    flex-shrink: 0;
  }
  
  .favicon {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    flex-shrink: 0;
    object-fit: cover;
  }
  
  .title {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    flex: 1;
    min-width: 0;
    /* Single line with ellipsis */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  /* ===========================================
     Card Content: Description + Image
     =========================================== */
  
  .card-content {
    display: flex;
    gap: 12px;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
  
  .description {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.4;
    flex: 1;
    min-width: 0;
    margin: 0;
    /* Limit to 4 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .preview-image {
    width: 100px;
    min-width: 100px;
    height: 100px;
    border-radius: 8px;
    overflow: hidden;
    background-color: var(--color-grey-20);
    flex-shrink: 0;
  }
  
  .preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }
  
  /* When no image, description takes full width */
  .card-content:not(:has(.preview-image)) .description {
    -webkit-line-clamp: 5;
    line-clamp: 5;
  }
</style>

