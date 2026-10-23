<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte

  Preview card for a single image_result embed.
  Always wraps in UnifiedEmbedPreview for consistent styling across all contexts:
  grid cards inside search fullscreens, standalone inline previews, etc.

  Displays the complete image across the full preview container. Source and
  title remain available in the fullscreen view and image alternative text.

  External images pass through the privacy proxy here. Callers may also supply
  already-proxied URLs; proxyImage avoids wrapping those again.

  Architecture: See docs/architecture/embeds.md
-->

<script lang="ts">
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';

  interface Props {
    /** Unique embed ID */
    id?: string;
    /** Image title */
    title?: string;
    /** Source domain name (e.g., "flickr.com") */
    sourceDomain?: string;
    /** Thumbnail URL, raw or already proxied */
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
  let displayImage = $derived(proxyImage(imageUrl || thumbnailUrl, MAX_WIDTH_PREVIEW_THUMBNAIL));

  function handleStop() {
    // no-op for image results (already resolved server-side)
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
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
    <ResultEmbedCard title={title || "Image"} mediaOnly={true} mediaFit="contain">
      {#snippet media()}
    <div class="image-result-content">
      {#if displayImage && !imageFailed && status === 'finished'}
        <img
          data-testid="image-result-preview-image"
          src={displayImage}
          alt={title || ''}
          class="result-image"
          class:visible={imageLoaded}
          onload={handleLoad}
          onerror={handleFail}
          use:handleImageError
        />

      {:else if status === 'processing'}
        <div class="skeleton-image"></div>
      {:else}
        <div class="image-placeholder">
          <span class="placeholder-icon clickable-icon icon_image"></span>
        </div>
      {/if}
    </div>
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .image-result-content {
    width: 100%;
    height: 100%;
    position: relative;
    overflow: hidden;
  }

  .result-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
    opacity: 0;
    transition: opacity var(--duration-normal) var(--easing-default);
    background: color-mix(in srgb, var(--color-grey-20) 27.272727%, var(--color-grey-25));
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
    background: color-mix(in srgb, var(--color-grey-20) 27.272727%, var(--color-grey-25));
  }

  .placeholder-icon {
    width: 28px;
    height: 28px;
    background: var(--color-grey-40, #bbb) !important;
  }



  .skeleton-image {
    width: 100%;
    height: 100%;
    background: color-mix(in srgb, var(--color-grey-20) 27.272727%, var(--color-grey-25));
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1; }
  }

  :global([data-theme="dark"]) .result-image {
    background: var(--color-grey-20);
  }

  :global([data-theme="dark"]) .skeleton-image,
  :global([data-theme="dark"]) .image-placeholder {
    background: var(--color-grey-20);
  }

  :global([data-theme="dark"]) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }
</style>
