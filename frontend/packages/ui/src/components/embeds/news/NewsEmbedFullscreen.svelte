<!--
  frontend/packages/ui/src/components/embeds/news/NewsEmbedFullscreen.svelte
  
  Fullscreen view for individual News article embeds.
  Uses UnifiedEmbedFullscreen as base and provides news-specific content.
  
  Shows:
  - Article title, favicon, and URL
  - Thumbnail image (if available)
  - Description/snippet
  - "Read article" button to open in new tab
  
  Used as child fullscreen from NewsSearchEmbedFullscreen via ChildEmbedOverlay pattern.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * Props for news embed fullscreen
   */
  interface Props {
    /** Article URL */
    url: string;
    /** Article title */
    title?: string;
    /** Article description */
    description?: string;
    /** Favicon URL */
    favicon?: string;
    /** Thumbnail image URL */
    thumbnail?: string;
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
    thumbnail,
    onClose,
    embedId
  }: Props = $props();
  
  // Get display values with fallbacks
  let displayTitle = $derived(title || getHostname(url));
  let displayDescription = $derived(description || '');
  let faviconUrl = $derived(
    favicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(url)}`
  );
  let thumbnailUrl = $derived(
    thumbnail || 
    `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(url)}`
  );
  
  /**
   * Safely extract hostname from URL
   */
  function getHostname(urlStr: string): string {
    try {
      return new URL(urlStr).hostname;
    } catch {
      return urlStr;
    }
  }
  
  // Handle opening article in new tab
  function handleOpenArticle() {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle share - opens share settings menu for this specific news embed
  async function handleShare() {
    try {
      console.debug('[NewsEmbedFullscreen] Opening share settings for news embed:', {
        embedId,
        url,
        title: displayTitle,
        description: displayDescription
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[NewsEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this news article. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'news',
        embed_id: embedId,
        url: url,
        title: displayTitle,
        description: displayDescription,
        favicon: faviconUrl,
        thumbnail: thumbnailUrl
      };

      // Store embed context for SettingsShare
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', 'Share News Article', 'share', 'settings.share.share_news.text');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[NewsEmbedFullscreen] Opened share settings for news embed');
    } catch (error) {
      console.error('[NewsEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

<!-- 
  NewsEmbedFullscreen uses UnifiedEmbedFullscreen as base
  Shows article title in header, with favicon, URL, and "Read article" button
  
  BasicInfosBar at bottom shows:
  - App icon (news app gradient)
  - Article favicon next to title
  - Article title (from displayTitle)
  - No status text (showStatus=false) since this is an individual article, not a skill
-->
<UnifiedEmbedFullscreen
  appId="news"
  skillId="article"
  title={displayTitle}
  {onClose}
  onShare={handleShare}
  skillIconName="article"
  skillName={displayTitle}
  faviconUrl={faviconUrl}
  showSkillIcon={false}
  showStatus={false}
>
  {#snippet headerExtra()}
    <div class="news-header-info">
      {#if faviconUrl}
        <img src={faviconUrl} alt="" class="favicon" />
      {/if}
      <div class="url">{getHostname(url)}</div>
    </div>
    
    <button class="read-button" onclick={handleOpenArticle}>
      {$text('embeds.read_article.text') || 'Read article'}
    </button>
  {/snippet}
  
  <!-- eslint-disable-next-line @typescript-eslint/no-unused-vars -->
  {#snippet content(_)}
    <!-- Thumbnail image -->
    {#if thumbnailUrl}
      <div class="thumbnail-container">
        <img 
          src={thumbnailUrl} 
          alt={displayTitle}
          class="thumbnail-image"
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
    
    <!-- Read button (duplicate for better UX) -->
    <div class="action-section">
      <button class="read-button" onclick={handleOpenArticle}>
        {$text('embeds.read_article.text') || 'Read article'}
      </button>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* Header extra content */
  .news-header-info {
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
  
  /* Read button */
  .read-button {
    margin-top: 12px;
    padding: 12px 24px;
    background-color: var(--color-button-primary);
    color: var(--color-font-button);
    border: none;
    border-radius: 20px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
  }
  
  .read-button:hover {
    background-color: var(--color-button-primary-hover);
    transform: translateY(-2px);
  }
  
  .read-button:active {
    background-color: var(--color-button-primary-pressed);
    transform: translateY(0);
    filter: none;
  }
  
  /* Thumbnail image */
  .thumbnail-container {
    width: 100%;
    max-width: 780px;
    margin: 20px auto 16px;
    border-radius: 12px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  
  .thumbnail-image {
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
    margin: 16px auto;
    max-width: 780px;
    padding: 0 16px;
  }
  
  /* Action section */
  .action-section {
    margin: 24px auto 16px;
    max-width: 780px;
    padding: 0 16px;
    display: flex;
    justify-content: center;
  }
</style>

