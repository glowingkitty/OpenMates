<!--
  frontend/packages/ui/src/components/embeds/WebsiteEmbedFullscreen.svelte
  
  Fullscreen view for Website embeds.
  Uses UnifiedEmbedFullscreen as base and provides website-specific content.
  
  Shows:
  - Website title, favicon, and URL
  - Preview image (if available)
  - Description
  - Snippets (if available)
  - "Open in new tab" button
-->

<script lang="ts">
  import { get } from 'svelte/store';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * Props for website embed fullscreen
   */
  interface Props {
    /** Website URL */
    url: string;
    /** Website title */
    title?: string;
    /** Website description */
    description?: string;
    /** Favicon URL */
    favicon?: string;
    /** Preview image URL */
    image?: string;
    /** Snippets array */
    snippets?: string[];
    /** Meta URL favicon (alternative source) */
    meta_url_favicon?: string;
    /** Thumbnail original (alternative image source) */
    thumbnail_original?: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
    embedId?: string;
  }
  
  let {
    url,
    title,
    description,
    favicon,
    image,
    snippets = [],
    meta_url_favicon,
    thumbnail_original,
    onClose,
    embedId
  }: Props = $props();
  
  // Get display values
  let displayTitle = $derived(title || new URL(url).hostname);
  let displayDescription = $derived(description || '');
  let faviconUrl = $derived(
    meta_url_favicon || 
    favicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(url)}`
  );
  let imageUrl = $derived(
    thumbnail_original || 
    image || 
    `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(url)}`
  );
  
  // Handle opening website in new tab
  function handleOpenInNewTab() {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle share - opens share settings menu for this specific website embed
  async function handleShare() {
    try {
      console.debug('[WebsiteEmbedFullscreen] Opening share settings for website embed:', {
        embedId,
        url,
        title: displayTitle,
        description: displayDescription
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[WebsiteEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this website embed. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'website',
        embed_id: embedId,
        url: url,
        title: displayTitle,
        description: displayDescription,
        favicon: faviconUrl,
        image: imageUrl,
        snippets: snippets
      };

      // Store embed context for SettingsShare
      (window as any).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', 'Share Website', 'share', 'settings.share.share_website.text');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[WebsiteEmbedFullscreen] Opened share settings for website embed');
    } catch (error) {
      console.error('[WebsiteEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="web"
  skillId="website"
  title={displayTitle}
  {onClose}
  onShare={handleShare}
>
  {#snippet headerExtra()}
    <div class="website-header-info">
      {#if faviconUrl}
        <img src={faviconUrl} alt="" class="favicon" />
      {/if}
      <div class="url">{new URL(url).hostname}</div>
    </div>
    
    <button class="open-button" onclick={handleOpenInNewTab}>
      Open in new tab
    </button>
  {/snippet}
  
  {#snippet content()}
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
    {#if snippets && snippets.length > 0}
      <div class="snippets">
        <h3>Snippets</h3>
        {#each snippets as snippet}
          <div class="snippet">{snippet}</div>
        {/each}
      </div>
    {/if}
    
    <!-- Open button (duplicate for better UX) -->
    <div class="action-section">
      <button class="open-button" onclick={handleOpenInNewTab}>
        Open in new tab
      </button>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* Header extra content */
  .website-header-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
  }
  
  .favicon {
    width: 24px;
    height: 24px;
    border-radius: 4px;
    flex-shrink: 0;
  }
  
  .url {
    font-size: 14px;
    color: var(--color-font-secondary);
  }
  
  /* Open button */
  .open-button {
    margin-top: 12px;
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
  
  /* Preview image */
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
  
  /* Description */
  .description {
    font-size: 16px;
    line-height: 1.6;
    color: var(--color-font-primary);
    margin-bottom: 16px;
  }
  
  /* Snippets */
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
  
  /* Action section */
  .action-section {
    margin-top: 24px;
    margin-bottom: 16px;
  }
</style>

