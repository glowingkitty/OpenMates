<!--
  Shared bounded thumbnail strip for web, news, and image search previews.
  Receives lightweight parent metadata; never fetches or decrypts children.
  URLs are deduplicated by the caller and proxied at thumbnail resolution.
  Native lazy loading avoids fetching offscreen search result thumbnails.
  Architecture: docs/architecture/embeds.md
-->
<script lang="ts">
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../utils/imageProxy';
  import { handleImageError } from '../../utils/offlineImageHandler';
  let { images, appId }: {
    images: Array<{ url: string; title: string }>;
    appId: string;
  } = $props();
</script>

<div class="thumbnail-strip" data-testid={`${appId}-search-thumbnail-strip`}>
  {#each images as image (image.url)}
    <img src={proxyImage(image.url, MAX_WIDTH_PREVIEW_THUMBNAIL)} alt={image.title}
      data-testid={`${appId}-search-thumbnail`} loading="lazy" decoding="async"
      use:handleImageError />
  {/each}
</div>

<style>
  .thumbnail-strip {
    display: flex;
    gap: var(--spacing-1);
    width: 100%;
    height: 30px;
    flex-shrink: 0;
    overflow: hidden;
  }
  img {
    height: 30px;
    width: 40px;
    flex-shrink: 0;
    object-fit: cover;
    display: block;
  }
</style>
