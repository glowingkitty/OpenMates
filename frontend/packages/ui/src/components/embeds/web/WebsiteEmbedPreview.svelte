<!--
  frontend/packages/ui/src/components/embeds/WebsiteEmbedPreview.svelte
  
  Preview component for Website embeds.
  Uses UnifiedEmbedPreview as base and provides website-specific details content.
  
  Features:
  - Auto-fetches metadata from preview server when not provided
  - Displays title, description, favicon and OG image
  - Proxies images through preview server to prevent direct external connections
  
  Details content structure:
  - Processing/Loading: URL hostname
  - Finished: title + description + preview image (if available)
  - Error: hostname with error styling
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  
  // ===========================================
  // Types
  // ===========================================
  
  /**
   * Metadata response from preview server
   */
  interface MetadataResponse {
    url: string;
    title?: string;
    description?: string;
    image?: string;
    favicon?: string;
    site_name?: string;
  }
  
  /**
   * Props for website embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Website URL */
    url: string;
    /** Website title (if not provided, will be fetched from preview server) */
    title?: string;
    /** Website description (if not provided, will be fetched from preview server) */
    description?: string;
    /** Favicon URL (if not provided, will be fetched from preview server) */
    favicon?: string;
    /** Preview image URL (if not provided, will be fetched from preview server) */
    image?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  // ===========================================
  // Props and State
  // ===========================================
  
  let {
    id,
    url,
    title,
    description,
    favicon,
    image,
    status,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // State for fetched metadata (when props are not provided)
  let fetchedTitle = $state<string | undefined>(undefined);
  let fetchedDescription = $state<string | undefined>(undefined);
  let fetchedFavicon = $state<string | undefined>(undefined);
  let fetchedImage = $state<string | undefined>(undefined);
  let isLoadingMetadata = $state(false);
  let metadataError = $state(false);
  
  // Track which URL we've fetched metadata for to avoid re-fetching
  let fetchedForUrl = $state<string | null>(null);
  
  // Map skillId to icon name
  const skillIconName = 'website';
  
  // ===========================================
  // Metadata Fetching
  // ===========================================
  
  /**
   * Determine if we need to fetch metadata from the preview server.
   * We fetch when:
   * - No title, description, and image are provided as props
   * - The URL hasn't been fetched yet
   * - Not currently loading
   */
  let needsMetadataFetch = $derived.by(() => {
    // If we already have metadata from props, no need to fetch
    if (title || description || image) {
      return false;
    }
    // If we already fetched for this URL, no need to re-fetch
    if (fetchedForUrl === url) {
      return false;
    }
    // If currently loading, don't trigger another fetch
    if (isLoadingMetadata) {
      return false;
    }
    return true;
  });
  
  /**
   * Fetch metadata from the preview server when needed.
   * Uses the /api/v1/metadata endpoint which extracts OG tags, title, etc.
   * Images and favicons are loaded via their respective proxy endpoints.
   */
  async function fetchMetadata() {
    if (!url) return;
    
    isLoadingMetadata = true;
    metadataError = false;
    
    // CRITICAL: Mark this URL as fetched BEFORE the request to prevent infinite loops
    // Even if the fetch fails, we don't want to retry indefinitely
    const urlToFetch = url;
    fetchedForUrl = urlToFetch;
    
    console.debug('[WebsiteEmbedPreview] Fetching metadata for URL:', urlToFetch);
    
    try {
      // Use GET endpoint to avoid CORS preflight (POST with JSON requires OPTIONS preflight)
      const response = await fetch(
        `https://preview.openmates.org/api/v1/metadata?url=${encodeURIComponent(urlToFetch)}`
      );
      
      if (!response.ok) {
        console.warn('[WebsiteEmbedPreview] Metadata fetch failed:', response.status, response.statusText);
        metadataError = true;
        return;
      }
      
      const data: MetadataResponse = await response.json();
      
      // Store fetched values
      fetchedTitle = data.title;
      fetchedDescription = data.description;
      fetchedFavicon = data.favicon;
      fetchedImage = data.image;
      
      console.info('[WebsiteEmbedPreview] Successfully fetched metadata:', {
        url: urlToFetch.substring(0, 50) + '...',
        title: data.title?.substring(0, 50) || 'No title',
        hasDescription: !!data.description,
        hasImage: !!data.image,
        hasFavicon: !!data.favicon
      });
      
    } catch (error) {
      console.error('[WebsiteEmbedPreview] Error fetching metadata:', error);
      metadataError = true;
    } finally {
      isLoadingMetadata = false;
    }
  }
  
  // Trigger metadata fetch when needed
  $effect(() => {
    if (needsMetadataFetch) {
      fetchMetadata();
    }
  });
  
  // ===========================================
  // Derived Display Values
  // ===========================================
  
  // Use prop values if provided, otherwise use fetched values
  let effectiveTitle = $derived(title || fetchedTitle);
  let effectiveDescription = $derived(description || fetchedDescription);
  let effectiveFavicon = $derived(favicon || fetchedFavicon);
  let effectiveImage = $derived(image || fetchedImage);
  
  // Get hostname for fallback display
  let hostname = $derived.by(() => {
    try {
      return new URL(url).hostname;
    } catch {
      return url;
    }
  });
  
  // Display title: use effective title or fall back to hostname
  let displayTitle = $derived(effectiveTitle || hostname);
  
  // Favicon URL: use effective favicon or fall back to preview server endpoint
  let faviconUrl = $derived(
    effectiveFavicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(url)}`
  );
  
  // Preview image URL - proxy through preview server with max_width for optimization
  // The preview thumbnail is 100x100px, so we request 200px for retina displays
  // Note: We only proxy if we have an actual image URL (not the webpage URL itself)
  const PREVIEW_IMAGE_MAX_WIDTH = 200; // 2x for retina displays (100px container)
  
  let imageUrl = $derived.by(() => {
    if (!effectiveImage) {
      return null; // No fallback to webpage URL - would cause 415 error
    }
    // Proxy through preview server with max_width to optimize image size
    return `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(effectiveImage)}&max_width=${PREVIEW_IMAGE_MAX_WIDTH}`;
  });
  
  // Compute effective status: if we're loading metadata, show as processing
  // But only if the original status was 'finished' (don't override explicit processing state)
  // If metadata fetch failed but we still have some data (or the original status was finished),
  // show as finished to display what we have (hostname at minimum)
  let effectiveStatus = $derived.by(() => {
    if (isLoadingMetadata && status === 'finished') {
      return 'processing';
    }
    // If metadata fetch failed, still show as finished so user sees the hostname/link
    // Don't show error state just because metadata couldn't be fetched
    if (metadataError && status === 'finished') {
      return 'finished';
    }
    return status;
  });
  
  // ===========================================
  // Event Handlers
  // ===========================================
  
  // Handle stop button click (not applicable for websites, but included for consistency)
  async function handleStop() {
    // Websites don't have cancellable tasks, but we include this for API consistency
    console.debug('[WebsiteEmbedPreview] Stop requested (not applicable for websites)');
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="web"
  skillId="website"
  skillIconName={skillIconName}
  status={effectiveStatus}
  skillName={displayTitle}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  faviconUrl={faviconUrl}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="website-details" class:mobile={isMobileLayout}>
      {#if effectiveStatus === 'processing'}
        <!-- Processing/Loading state: show hostname only -->
        <div class="website-hostname">{hostname}</div>
      {:else if effectiveStatus === 'finished'}
        <!-- Finished state: description on left, image on right (if available) -->
        <!-- Title and favicon are shown in BasicInfosBar, not here -->
        <div class="website-content-row">
          {#if effectiveDescription}
            <div class="website-description">{effectiveDescription}</div>
          {/if}
          
          {#if imageUrl && !isMobileLayout}
            <!-- Preview image on the right (desktop only) -->
            <div class="website-preview-image">
              <img 
                src={imageUrl} 
                alt={displayTitle}
                loading="lazy"
                onerror={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            </div>
          {/if}
        </div>
      {:else}
        <!-- Error state -->
        <div class="website-error">{hostname}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Website Details Content
     =========================================== */
  
  .website-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .website-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .website-details.mobile {
    justify-content: flex-start;
  }
  
  /* Website content row: description on left, image on right */
  .website-content-row {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    margin-top: 8px;
    flex: 1;
    min-height: 0;
  }
  
  /* Website description on the left */
  .website-description {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.4;
    flex: 1;
    min-width: 0;
    /* Limit to 3 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .website-details.mobile .website-description {
    font-size: 12px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Preview image on the right (desktop only) */
  .website-preview-image {
    width: 100px;
    min-width: 100px;
    height: 100px;
    border-radius: 8px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    flex-shrink: 0;
  }
  
  .website-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }
  
  /* When no image, description takes full width */
  .website-content-row:not(:has(.website-preview-image)) .website-description {
    flex: 1;
    max-width: 100%;
  }
  
  /* Website hostname (for processing state) */
  .website-hostname {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .website-details.mobile .website-hostname {
    font-size: 12px;
  }
  
  /* Error state */
  .website-error {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
</style>

