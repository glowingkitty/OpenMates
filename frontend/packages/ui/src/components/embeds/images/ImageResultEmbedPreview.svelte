<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte

  Preview card for a single image_result embed.
  Displays a thumbnail image covering the full preview container,
  similar to ImageEmbedPreview's full-bleed image style.

  Two rendering modes:
  - Grid card (default): used by GroupRenderer / ImagesSearchEmbedFullscreen as
    child cards. No UnifiedEmbedPreview wrapper; caller provides layout.
  - Standalone (standalone=true): used by AppSkillUseRenderer when rendering
    a [!](embed:ref) large preview. Wraps in UnifiedEmbedPreview with
    hasFullWidthImage for the standard embed shell (status bar, hover, etc.).

  External images are proxied by the caller (ImagesSearchEmbedFullscreen)
  or via proxyImage() for standalone mode.

  Architecture: See docs/architecture/embeds.md
-->

<script lang="ts">
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  interface Props {
    /** Unique embed ID (required for standalone mode) */
    id?: string;
    /** Image title */
    title?: string;
    /** Source domain name (e.g., "flickr.com") */
    sourceDomain?: string;
    /** Proxied thumbnail URL (caller must proxy before passing) */
    thumbnailUrl?: string;
    /** Full-size image URL (used in standalone mode for expanded view) */
    imageUrl?: string;
    /** Favicon URL for the source site */
    faviconUrl?: string;
    /** Processing status (standalone mode) */
    status?: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation (standalone mode) */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
    /** Standalone mode: wrap in UnifiedEmbedPreview with full embed shell */
    standalone?: boolean;
  }

  let {
    id = '',
    title,
    sourceDomain,
    thumbnailUrl,
    imageUrl,
    faviconUrl,
    status = 'finished',
    taskId = '',
    isMobile = false,
    onFullscreen,
    standalone = false,
  }: Props = $props();

  let imageLoaded = $state(false);
  let imageFailed = $state(false);

  function handleLoad() {
    imageLoaded = true;
  }

  function handleFail() {
    imageFailed = true;
  }

  /** The display image — prefer full-size imageUrl, fallback to thumbnailUrl */
  let displayImage = $derived(imageUrl || thumbnailUrl);
</script>

{#if standalone}
  <!-- Standalone mode: full embed shell via UnifiedEmbedPreview -->
  <UnifiedEmbedPreview
    {id}
    appId="images"
    skillId="image_result"
    skillIconName="image"
    {status}
    skillName={sourceDomain || 'Image'}
    {isMobile}
    showSkillIcon={false}
    faviconUrl={faviconUrl}
    showStatus={false}
    hasFullWidthImage={true}
    {taskId}
    onFullscreen={onFullscreen}
  >
    {#snippet details()}
      <div class="image-result-standalone">
        {#if displayImage && !imageFailed && status === 'finished'}
          <img
            src={displayImage}
            alt={title || ''}
            class="result-image"
            class:visible={imageLoaded}
            onload={handleLoad}
            onerror={handleFail}
            use:handleImageError
          />
          {#if imageLoaded && (title || sourceDomain)}
            <div class="card-overlay card-overlay--standalone">
              {#if sourceDomain || faviconUrl}
                <div class="source-line">
                  {#if faviconUrl}
                    <img src={faviconUrl} alt="" class="favicon favicon--standalone" use:handleImageError />
                  {/if}
                  {#if sourceDomain}
                    <span class="source-domain source-domain--standalone">{sourceDomain}</span>
                  {/if}
                </div>
              {/if}
              {#if title}
                <span class="result-title result-title--standalone">{title}</span>
              {/if}
            </div>
          {/if}
        {:else if status === 'processing'}
          <div class="skeleton-image"></div>
        {:else}
          <div class="image-placeholder">
            <span class="placeholder-icon clickable-icon icon_image"></span>
          </div>
        {/if}
      </div>
    {/snippet}
  </UnifiedEmbedPreview>
{:else}
  <!-- Grid card mode: no wrapper, caller provides layout -->
  <div class="image-result-card">
    {#if thumbnailUrl && !imageFailed}
      <img
        src={thumbnailUrl}
        alt={title || ''}
        class="result-image"
        class:visible={imageLoaded}
        onload={handleLoad}
        onerror={handleFail}
        use:handleImageError
      />
    {:else}
      <div class="image-placeholder">
        <span class="placeholder-icon clickable-icon icon_image"></span>
      </div>
    {/if}

    {#if (title || sourceDomain) && imageLoaded}
      <div class="card-overlay">
        {#if sourceDomain}
          <div class="source-line">
            {#if faviconUrl}
              <img src={faviconUrl} alt="" class="favicon" use:handleImageError />
            {/if}
            <span class="source-domain">{sourceDomain}</span>
          </div>
        {/if}
        {#if title}
          <span class="result-title">{title}</span>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  /* -- Grid card mode -- */
  .image-result-card {
    position: relative;
    width: 100%;
    aspect-ratio: 4/3;
    border-radius: 10px;
    overflow: hidden;
    background: var(--color-grey-15, #ebebeb);
  }

  /* -- Standalone mode -- */
  .image-result-standalone {
    width: 100%;
    height: 100%;
    position: relative;
    overflow: hidden;
    border-radius: 30px 30px 0 0;
  }

  /* -- Shared image styles -- */
  .result-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  .result-image.visible {
    opacity: 1;
  }

  .image-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-15, #ebebeb);
  }

  .placeholder-icon {
    width: 28px;
    height: 28px;
    background: var(--color-grey-40, #bbb) !important;
  }

  /* -- Overlay -- */
  .card-overlay {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 20px 10px 8px;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.55));
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .card-overlay--standalone {
    padding: 32px 20px 16px;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.6));
    gap: 4px;
  }

  .source-line {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .favicon {
    width: 12px;
    height: 12px;
    flex-shrink: 0;
    object-fit: contain;
    border-radius: 2px;
  }

  .favicon--standalone {
    width: 14px;
    height: 14px;
  }

  .source-domain {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.75);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }

  .source-domain--standalone {
    font-size: 12px;
  }

  .result-title {
    font-size: 11px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  .result-title--standalone {
    font-size: 14px;
    line-height: 1.4;
  }

  /* -- Skeleton loading -- */
  .skeleton-image {
    width: 100%;
    height: 100%;
    background: var(--color-grey-15, #ebebeb);
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1; }
  }

  /* -- Dark mode -- */
  :global(.dark) .image-result-card,
  :global(.dark) .skeleton-image,
  :global(.dark) .image-placeholder {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }
</style>
