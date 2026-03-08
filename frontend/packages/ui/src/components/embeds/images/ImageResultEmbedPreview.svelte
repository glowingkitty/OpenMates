<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte

  Preview card for a single image_result child embed.
  Displays a thumbnail image covering the full preview container,
  similar to ImageEmbedPreview's full-bleed image style.

  Used by ImagesSearchEmbedFullscreen as child cards in the image grid.
  External images are proxied by the caller (ImagesSearchEmbedFullscreen).

  Architecture: See docs/architecture/embeds.md
-->

<script lang="ts">
  import { handleImageError } from '../../../utils/offlineImageHandler';

  interface Props {
    /** Image title */
    title?: string;
    /** Source domain name (e.g., "flickr.com") */
    sourceDomain?: string;
    /** Proxied thumbnail URL (caller must proxy before passing) */
    thumbnailUrl?: string;
    /** Favicon URL for the source site */
    faviconUrl?: string;
  }

  let {
    title,
    sourceDomain,
    thumbnailUrl,
    faviconUrl
  }: Props = $props();

  let imageLoaded = $state(false);
  let imageFailed = $state(false);

  function handleLoad() {
    imageLoaded = true;
  }

  function handleFail() {
    imageFailed = true;
  }
</script>

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
    <!-- Fallback placeholder -->
    <div class="image-placeholder">
      <span class="placeholder-icon clickable-icon icon_image"></span>
    </div>
  {/if}

  <!-- Overlay info at bottom -->
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

<style>
  .image-result-card {
    position: relative;
    width: 100%;
    aspect-ratio: 4/3;
    border-radius: 10px;
    overflow: hidden;
    background: var(--color-grey-15, #ebebeb);
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

  /* Fallback when image fails to load */
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

  /* Overlay at bottom with gradient for readability */
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

  .source-domain {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.75);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
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

  /* Dark mode */
  :global(.dark) .image-result-card {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .image-placeholder {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }
</style>
