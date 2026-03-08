<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte

  Preview card for a single image_result child embed.
  Displays thumbnail image, title, and source domain.

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
  <!-- Image area -->
  <div class="image-area" class:loaded={imageLoaded} class:failed={imageFailed}>
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
  </div>

  <!-- Source info below image -->
  <div class="card-info">
    {#if faviconUrl || sourceDomain}
      <div class="source-line">
        {#if faviconUrl}
          <img src={faviconUrl} alt="" class="favicon" use:handleImageError />
        {/if}
        {#if sourceDomain}
          <span class="source-domain">{sourceDomain}</span>
        {/if}
      </div>
    {/if}
    {#if title}
      <span class="result-title">{title}</span>
    {/if}
  </div>
</div>

<style>
  .image-result-card {
    display: flex;
    flex-direction: column;
    border-radius: 10px;
    overflow: hidden;
    background: var(--color-grey-5, #fafafa);
    border: 1px solid var(--color-grey-15, #eee);
    width: 100%;
  }

  /* Image area: fixed aspect ratio container */
  .image-area {
    width: 100%;
    aspect-ratio: 4/3;
    overflow: hidden;
    position: relative;
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

  /* Source info */
  .card-info {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-height: 0;
  }

  .source-line {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .favicon {
    width: 12px;
    height: 12px;
    flex-shrink: 0;
    object-fit: contain;
  }

  .source-domain {
    font-size: 10px;
    color: var(--color-grey-50, #888);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }

  .result-title {
    font-size: 11px;
    font-weight: 500;
    color: var(--color-grey-80, #333);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  /* Dark mode */
  :global(.dark) .image-result-card {
    background: var(--color-grey-90, #1a1a1a);
    border-color: var(--color-grey-80, #333);
  }

  :global(.dark) .image-area,
  :global(.dark) .image-placeholder {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }

  :global(.dark) .result-title {
    color: var(--color-grey-20, #ddd);
  }

  :global(.dark) .source-domain {
    color: var(--color-grey-50, #888);
  }
</style>
