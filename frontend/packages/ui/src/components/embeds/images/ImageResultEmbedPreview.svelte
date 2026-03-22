<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte

  Preview card for a single image_result embed.
  Always wraps in UnifiedEmbedPreview for consistent styling across all contexts:
  grid cards inside search fullscreens, standalone inline previews, etc.

  Displays a thumbnail image covering the full preview container with a gradient
  overlay showing the source domain and title at the bottom.

  External images must be proxied by the caller (ImagesSearchEmbedFullscreen
  proxies via proxyImage(), AppSkillUseRenderer proxies for standalone use).

  Architecture: See docs/architecture/embeds.md
-->

<script lang="ts">
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  interface Props {
    /** Unique embed ID */
    id?: string;
    /** Image title */
    title?: string;
    /** Source domain name (e.g., "flickr.com") */
    sourceDomain?: string;
    /** Proxied thumbnail URL (caller must proxy before passing) */
    thumbnailUrl?: string;
    /** Full-size image URL (fallback display image) */
    imageUrl?: string;
    /** Favicon URL for the source site */
    faviconUrl?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
    /**
     * @deprecated No longer used. Kept for backward compatibility — always renders
     * with UnifiedEmbedPreview. Will be removed in a future cleanup.
     */
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

  function handleStop() {
    // no-op for image results (already resolved server-side)
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="images"
  skillId="image_result"
  skillIconName="image"
  {status}
  skillName={sourceDomain || 'Image'}
  {isMobile}
  showSkillIcon={false}
  {faviconUrl}
  showStatus={false}
  hasFullWidthImage={true}
  {taskId}
  {onFullscreen}
  onStop={handleStop}
>
  {#snippet details()}
    <div class="image-result-content">
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
        {#if imageLoaded && title}
          <div class="card-overlay">
            <span class="result-title">{title}</span>
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

<style>
  .image-result-content {
    width: 100%;
    height: 100%;
    position: relative;
    overflow: hidden;
    border-radius: 30px 30px 0 0;
  }

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

  .card-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    padding: 12px 14px 32px;
    background: linear-gradient(rgba(0, 0, 0, 0.5), transparent);
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .result-title {
    font-size: 12px;
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

  :global(.dark) .skeleton-image,
  :global(.dark) .image-placeholder {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }
</style>
