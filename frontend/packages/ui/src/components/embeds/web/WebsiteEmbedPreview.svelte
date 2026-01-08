<!--
  frontend/packages/ui/src/components/embeds/WebsiteEmbedPreview.svelte
  
  Preview component for Website embeds.
  Uses UnifiedEmbedPreview as base and provides website-specific details content.
  
  Features:
  - Auto-fetches metadata from preview server when not provided
  - Displays title, description, favicon and OG image
  - Proxies images through preview server to prevent direct external connections
  - Large thumbnail image on the RIGHT side of the preview card
  - Passes fetched metadata to fullscreen view for consistent display
  
  Details content structure:
  - Processing/Loading: URL hostname
  - Finished: Description on LEFT, larger thumbnail image on RIGHT
  - Error: hostname with error styling
  
  Data Flow:
  - When preview fetches metadata (title, description, image), this data is passed
    to the fullscreen view via the customFullscreenData event detail.
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
   * Metadata passed to fullscreen when user clicks to open
   * Contains the effective values (props or fetched from preview server)
   */
  export interface WebsiteMetadata {
    title?: string;
    description?: string;
    favicon?: string;
    image?: string;
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
    /** Click handler for fullscreen - receives fetched metadata so fullscreen can display it */
    onFullscreen?: (metadata: WebsiteMetadata) => void;
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
  // The preview thumbnail is now larger (full-width ~260px), so we request 520px for retina displays
  // Note: We only proxy if we have an actual image URL (not the webpage URL itself)
  const PREVIEW_IMAGE_MAX_WIDTH = 520; // 2x for retina displays (260px container)
  
  let imageUrl = $derived.by(() => {
    if (!effectiveImage) {
      return null; // No fallback to webpage URL - would cause 415 error
    }
    // Proxy through preview server with max_width to optimize image size
    return `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(effectiveImage)}&max_width=${PREVIEW_IMAGE_MAX_WIDTH}`;
  });
  
  // Track image loading errors for graceful fallback
  let imageLoadError = $state(false);
  
  // Determine if we should use full-width image layout (no description, has image)
  // This is passed to UnifiedEmbedPreview to remove padding from details section
  let shouldUseFullWidthImage = $derived(
    !effectiveDescription && 
    !!imageUrl && 
    !imageLoadError && 
    !isMobile
  );
  
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
  
  /**
   * Handle fullscreen open - passes fetched metadata to fullscreen component
   * This ensures fullscreen displays the same data as the preview without re-fetching
   */
  function handleFullscreen() {
    if (!onFullscreen) return;
    
    // Pass the effective metadata values (props or fetched) to fullscreen
    const metadata: WebsiteMetadata = {
      title: effectiveTitle,
      description: effectiveDescription,
      favicon: effectiveFavicon,
      image: effectiveImage
    };
    
    console.debug('[WebsiteEmbedPreview] Opening fullscreen with metadata:', {
      title: metadata.title?.substring(0, 50) || 'none',
      hasDescription: !!metadata.description,
      hasImage: !!metadata.image,
      hasFavicon: !!metadata.favicon
    });
    
    onFullscreen(metadata);
  }
  
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
  onFullscreen={handleFullscreen}
  onStop={handleStop}
  showStatus={false}
  faviconUrl={faviconUrl}
  showSkillIcon={false}
  hasFullWidthImage={shouldUseFullWidthImage}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="website-details" class:mobile={isMobileLayout}>
      {#if effectiveStatus === 'processing'}
        <!-- Processing/Loading state: show hostname only -->
        <div class="website-hostname">{hostname}</div>
      {:else if effectiveStatus === 'finished'}
        <!-- Finished state: description on LEFT, larger image on RIGHT -->
        <!-- If no description, image takes FULL WIDTH -->
        <!-- Title and favicon are shown in BasicInfosBar, not here -->
        <div class="website-content-row" class:no-description={!effectiveDescription}>
          {#if effectiveDescription}
            <div class="website-description">{effectiveDescription}</div>
          {/if}
          
          {#if imageUrl && !imageLoadError && !isMobileLayout}
            <!-- Preview image: full width when no description, right side when description exists -->
            <div class="website-preview-image" class:full-width={!effectiveDescription}>
              <img 
                src={imageUrl} 
                alt={displayTitle}
                loading="lazy"
                onerror={() => {
                  imageLoadError = true;
                  console.debug('[WebsiteEmbedPreview] Image load error, hiding image');
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
    width: 100%; /* Ensure full width of parent */
  }
  
  /* Desktop layout: vertically centered content */
  .website-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .website-details.mobile {
    justify-content: flex-start;
  }
  
  /* ===========================================
     Website Content Row (description left, image right)
     =========================================== */
  
  .website-content-row {
    display: flex;
    align-items: stretch; /* Stretch items to fill height */
    flex: 1;
    min-height: 0;
    height: 100%;
    width: 100%; /* Ensure full width of parent */
  }
  
  /* ===========================================
     Website Description (Left side)
     =========================================== */
  
  .website-description {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.4;
    flex: 1;
    min-width: 0;
    /* Limit lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 6;
    line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
    /* Vertically align text to top */
    align-self: flex-start;
    padding-top: 10px;
  }
  
  .website-details.mobile .website-description {
    font-size: 12px;
    -webkit-line-clamp: 6;
    line-clamp: 6;
  }
  
  /* ===========================================
     Large Preview Image (Right side by default)
     =========================================== */
  
  .website-preview-image {
    width: 150px;
    height: 171px;
    transform: translateX(20px);
  }
  
  .website-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }
  
  /* ===========================================
     Full-Width Image (when no description)
     =========================================== */
  
  /* When no description, make content row fill available width */
  .website-content-row.no-description {
    width: 100%;
  }
  
  /* Full-width image styling when no description */
  .website-preview-image.full-width {
    width: 100%;
    min-width: 100%; /* Prevent flex shrinking */
    height: 100%; /* Fill parent height */
    transform: none; /* Remove the translateX offset */
  }
  
  .website-preview-image.full-width img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }
  
  /* When no image, description takes full width */
  .website-content-row:not(:has(.website-preview-image)) .website-description {
    flex: 1;
    max-width: 100%;
  }
  
  /* ===========================================
     Website Hostname (Processing state)
     =========================================== */
  
  .website-hostname {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .website-details.mobile .website-hostname {
    font-size: 12px;
  }
  
  /* ===========================================
     Error State
     =========================================== */
  
  .website-error {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
</style>

