<!--
  frontend/packages/ui/src/components/embeds/wiki/WikipediaFullscreen.svelte

  Fullscreen view for Wikipedia topic links. Fetches article data on-demand
  from Wikipedia's public CORS-friendly REST API when opened.

  Layout:
  - Hero thumbnail image (if available)
  - Article title + short Wikidata description
  - Extract text (article summary paragraph)
  - "Open on Wikipedia" CTA button
  - Loading skeleton while fetching

  This component does NOT use the embed system (no embed store, no encryption).
  Wikipedia content is public and fetched directly from the browser.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';

  interface Props {
    /** Canonical Wikipedia article title (e.g. "Albert_Einstein") */
    wikiTitle: string;
    /** The topic phrase as shown in the message */
    displayText: string;
    /** Thumbnail URL from batch validation (low-res preview) */
    thumbnailUrl?: string | null;
    /** Short description from batch validation */
    description?: string | null;
    /** Close handler */
    onClose: () => void;
  }

  let {
    wikiTitle,
    displayText,
    thumbnailUrl = null,
    description = null,
    onClose,
  }: Props = $props();

  // On-demand fetched data — initialized from props, overwritten by API fetch
  let isLoading = $state(true);
  let fetchError = $state<string | null>(null);
  let articleTitle = $derived.by(() => fetchedTitle || displayText);
  let articleDescription = $derived.by(() => fetchedDescription || description || '');
  let articleImageUrl = $derived.by(() => fetchedImageUrl || thumbnailUrl || '');
  let articleUrl = $derived(fetchedArticleUrl || `https://en.wikipedia.org/wiki/${encodeURIComponent(wikiTitle)}`);
  let articleExtract = $state('');

  // Fetched values (set by onMount, override prop defaults)
  let fetchedTitle = $state('');
  let fetchedDescription = $state('');
  let fetchedImageUrl = $state('');
  let fetchedArticleUrl = $state('');

  onMount(async () => {
    try {
      const response = await fetch(
        `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(wikiTitle)}`,
        {
          headers: {
            'Accept': 'application/json',
          },
        },
      );

      if (!response.ok) {
        if (response.status === 404) {
          fetchError = 'Article not found';
        } else {
          fetchError = `Failed to load (${response.status})`;
        }
        isLoading = false;
        return;
      }

      const data = await response.json();

      fetchedTitle = data.title || '';
      fetchedDescription = data.description || '';
      articleExtract = data.extract || '';
      fetchedArticleUrl = data.content_urls?.desktop?.page || '';

      // Prefer original image over thumbnail for fullscreen display
      if (data.originalimage?.source) {
        fetchedImageUrl = data.originalimage.source;
      } else if (data.thumbnail?.source) {
        fetchedImageUrl = data.thumbnail.source;
      }

      isLoading = false;
    } catch (err) {
      console.error('[WikipediaFullscreen] Failed to fetch article summary:', err);
      fetchError = 'Failed to load article';
      isLoading = false;
    }
  });

  // Proxied image URL for CORS/caching
  let proxiedImage = $derived(
    articleImageUrl ? proxyImage(articleImageUrl, MAX_WIDTH_HEADER_IMAGE) : '',
  );

  function handleOpenWikipedia() {
    window.open(articleUrl, '_blank', 'noopener,noreferrer');
  }
</script>

<UnifiedEmbedFullscreen
  appId="wiki"
  skillId="wikipedia"
  embedHeaderTitle={articleTitle}
  embedHeaderSubtitle={articleDescription}
  showSkillIcon={false}
  {onClose}
>
  {#snippet content()}
    <div class="wiki-fullscreen-content" data-testid="wiki-fullscreen-content">
      {#if isLoading}
        <!-- Loading skeleton -->
        <div class="wiki-skeleton">
          <div class="wiki-skeleton-image"></div>
          <div class="wiki-skeleton-title"></div>
          <div class="wiki-skeleton-desc"></div>
          <div class="wiki-skeleton-text"></div>
          <div class="wiki-skeleton-text short"></div>
        </div>
      {:else if fetchError}
        <div class="wiki-error">
          <p>{fetchError}</p>
        </div>
      {:else}
        <!-- Hero image -->
        {#if proxiedImage}
          <div class="wiki-image-container">
            <img
              src={proxiedImage}
              alt={articleTitle}
              class="wiki-hero-image"
              onerror={handleImageError}
            />
          </div>
        {/if}

        <!-- Title + description -->
        <div class="wiki-header">
          <h2 class="wiki-title" data-testid="wiki-fullscreen-title">{articleTitle}</h2>
          {#if articleDescription}
            <p class="wiki-description">{articleDescription}</p>
          {/if}
        </div>

        <!-- Extract (article summary) -->
        {#if articleExtract}
          <div class="wiki-extract">
            <p>{articleExtract}</p>
          </div>
        {/if}

        <!-- CTA: Open on Wikipedia -->
        <div class="wiki-cta">
          <EmbedHeaderCtaButton
            label="Open on Wikipedia"
            onclick={handleOpenWikipedia}
          />
        </div>

        <!-- Attribution -->
        <p class="wiki-attribution">
          Source: Wikipedia — content available under CC BY-SA 4.0
        </p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .wiki-fullscreen-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-16);
    max-width: 600px;
    margin: 0 auto;
    padding: var(--spacing-16);
  }

  /* Hero image */
  .wiki-image-container {
    width: 100%;
    max-width: 511px;
    border-radius: var(--radius-12);
    overflow: hidden;
  }

  .wiki-hero-image {
    width: 100%;
    height: auto;
    display: block;
    object-fit: cover;
    max-height: 340px;
  }

  /* Header: title + description */
  .wiki-header {
    width: 100%;
    text-align: left;
  }

  .wiki-title {
    font-size: var(--font-size-20);
    font-weight: 600;
    color: var(--color-grey-90);
    margin: 0 0 var(--spacing-4) 0;
    line-height: 1.3;
  }

  .wiki-description {
    font-size: var(--font-size-14);
    color: var(--color-grey-60);
    margin: 0;
    font-style: italic;
  }

  /* Extract text */
  .wiki-extract {
    width: 100%;
    text-align: left;
  }

  .wiki-extract p {
    font-size: var(--font-size-15);
    color: var(--color-grey-80);
    line-height: 1.65;
    margin: 0;
  }

  /* CTA button */
  .wiki-cta {
    width: 100%;
    display: flex;
    justify-content: center;
  }

  /* Attribution */
  .wiki-attribution {
    font-size: var(--font-size-12);
    color: var(--color-grey-40);
    text-align: center;
    margin: 0;
  }

  /* Error state */
  .wiki-error {
    text-align: center;
    padding: var(--spacing-32);
  }

  .wiki-error p {
    font-size: var(--font-size-15);
    color: var(--color-grey-50);
  }

  /* Loading skeleton */
  .wiki-skeleton {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-12);
  }

  .wiki-skeleton-image {
    width: 100%;
    height: 200px;
    border-radius: var(--radius-12);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
  }

  .wiki-skeleton-title {
    width: 60%;
    height: 24px;
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
    animation-delay: 0.1s;
  }

  .wiki-skeleton-desc {
    width: 40%;
    height: 16px;
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
    animation-delay: 0.2s;
  }

  .wiki-skeleton-text {
    width: 100%;
    height: 14px;
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
    animation-delay: 0.3s;
  }

  .wiki-skeleton-text.short {
    width: 75%;
  }

  @keyframes wiki-pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 0.8; }
  }
</style>
