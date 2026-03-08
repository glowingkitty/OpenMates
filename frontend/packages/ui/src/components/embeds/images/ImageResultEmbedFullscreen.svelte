<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedFullscreen.svelte

  Fullscreen view for a single image_result child embed.
  Shows the full-size proxied image, title, source domain, and a link to the source page.

  Used as a drill-down overlay from ImagesSearchEmbedFullscreen.
  External images are proxied by the caller (ImagesSearchEmbedFullscreen).

  Architecture: See docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { handleImageError } from '../../../utils/offlineImageHandler';

  interface Props {
    /** Image title */
    title?: string;
    /** Source domain name (e.g., "flickr.com") */
    sourceDomain?: string;
    /** Full URL of the source page (for the "View source" link) */
    sourcePageUrl?: string;
    /** Full-size proxied image URL (caller must proxy before passing) */
    imageUrl?: string;
    /** Proxied thumbnail URL (shown while full-size loads) */
    thumbnailUrl?: string;
    /** Favicon URL for the source site */
    faviconUrl?: string;
    /** Child embed ID */
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    onClose: () => void;
  }

  let {
    title,
    sourceDomain,
    sourcePageUrl,
    imageUrl,
    thumbnailUrl,
    faviconUrl,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    onClose
  }: Props = $props();

  let imageLoaded = $state(false);
  let imageFailed = $state(false);
  let showThumbnail = $state(true); // show thumbnail as placeholder until full image loads

  function handleImageLoad() {
    imageLoaded = true;
    showThumbnail = false;
  }

  function handleImageFail() {
    imageFailed = true;
    showThumbnail = false;
  }

  let embedHeaderTitle    = $derived(title || $text('embeds.image_search'));
  let embedHeaderSubtitle = $derived(sourceDomain || '');
</script>

<UnifiedEmbedFullscreen
  appId="images"
  skillId="image_result"
  {embedHeaderTitle}
  {embedHeaderSubtitle}
  skillIconName="image"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet content()}
    <div class="result-fullscreen">
      <!-- Image display section -->
      <div class="image-section">
        {#if imageUrl && !imageFailed}
          <!-- Progressive: thumbnail first, then full-size -->
          {#if showThumbnail && thumbnailUrl}
            <img
              src={thumbnailUrl}
              alt={title || ''}
              class="display-image blurred"
              use:handleImageError
            />
          {/if}
          <img
            src={imageUrl}
            alt={title || ''}
            class="display-image"
            class:hidden={!imageLoaded}
            onload={handleImageLoad}
            onerror={handleImageFail}
            use:handleImageError
          />
        {:else if thumbnailUrl && !imageFailed}
          <img
            src={thumbnailUrl}
            alt={title || ''}
            class="display-image"
            use:handleImageError
          />
        {:else}
          <div class="image-placeholder">
            <span class="placeholder-icon clickable-icon icon_image"></span>
          </div>
        {/if}
      </div>

      <!-- Metadata section -->
      <div class="meta-section">
        <!-- Source site info -->
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

        <!-- Title -->
        {#if title}
          <h2 class="result-title">{title}</h2>
        {/if}

        <!-- Source page link -->
        {#if sourcePageUrl}
          <a
            href={sourcePageUrl}
            target="_blank"
            rel="noopener noreferrer"
            class="source-link"
          >
            <span class="clickable-icon icon_web link-icon"></span>
            <span>{$text('embeds.image_search.view_source')}</span>
          </a>
        {/if}

        <!-- Open full image link -->
        {#if imageUrl}
          <a
            href={imageUrl}
            target="_blank"
            rel="noopener noreferrer"
            class="open-image-link"
          >
            <span class="clickable-icon icon_image open-icon"></span>
            <span>{$text('embeds.image_search.open_image')}</span>
          </a>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .result-fullscreen {
    display: flex;
    flex-direction: row;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }

  /* Image section — left column on wide, full-width on narrow */
  .image-section {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    padding: 24px;
    min-width: 0;
    overflow: hidden;
    background: var(--color-grey-5, #fafafa);
  }

  .display-image {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 10px;
    box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.15);
    display: block;
  }

  .display-image.blurred {
    filter: blur(4px);
    position: absolute;
    inset: 24px;
  }

  .display-image.hidden {
    opacity: 0;
  }

  /* Image fallback placeholder */
  .image-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 200px;
    height: 200px;
    background: var(--color-grey-15, #ebebeb);
    border-radius: 16px;
  }

  .placeholder-icon {
    width: 48px;
    height: 48px;
    background: var(--color-grey-40, #bbb) !important;
  }

  /* Metadata section — right column on wide, below image on narrow */
  .meta-section {
    width: 280px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 24px;
    overflow-y: auto;
    align-self: center;
  }

  .source-line {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .favicon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    object-fit: contain;
  }

  .source-domain {
    font-size: 13px;
    color: var(--color-grey-50, #888);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .result-title {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-90, #1a1a1a);
    line-height: 1.4;
    margin: 0;
    word-break: break-word;
  }

  .source-link,
  .open-image-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 500;
    color: var(--color-primary-50, #5b8dd9);
    text-decoration: none;
    padding: 6px 0;
  }

  .source-link:hover,
  .open-image-link:hover {
    text-decoration: underline;
  }

  .link-icon,
  .open-icon {
    width: 16px;
    height: 16px;
    background: var(--color-primary-50, #5b8dd9) !important;
    flex-shrink: 0;
  }

  /* Dark mode */
  :global(.dark) .image-section {
    background: var(--color-grey-95, #111);
  }

  :global(.dark) .display-image {
    box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.4);
  }

  :global(.dark) .image-placeholder {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }

  :global(.dark) .result-title {
    color: var(--color-grey-10, #f5f5f5);
  }

  :global(.dark) .source-domain {
    color: var(--color-grey-50, #888);
  }

  :global(.dark) .source-link,
  :global(.dark) .open-image-link {
    color: var(--color-primary-40, #7a9ed0);
  }

  :global(.dark) .link-icon,
  :global(.dark) .open-icon {
    background: var(--color-primary-40, #7a9ed0) !important;
  }

  /* Responsive: narrow containers — stack vertically */
  @container fullscreen (max-width: 560px) {
    .result-fullscreen {
      flex-direction: column;
      overflow-y: auto;
    }

    .image-section {
      flex: none;
      width: 100%;
      padding: 16px;
    }

    .meta-section {
      width: 100%;
      padding: 0 16px 16px 16px;
      align-self: stretch;
    }
  }
</style>
