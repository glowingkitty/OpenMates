<!--
  frontend/packages/ui/src/components/embeds/images/ImageViewEmbedPreview.svelte

  Preview card for the images/view skill result embed.
  Shown when the AI executes the images.view skill on a user-uploaded image.

  Displays:
  - Processing state: skeleton lines + "Viewing…" subtitle
  - Finished state: the decrypted preview image from the original upload embed
  - The filename from the skill embed data

  On click: opens the ORIGINAL uploaded image's fullscreen viewer
  (fires 'imagefullscreen' CustomEvent with the upload embed's data),
  NOT a new standalone fullscreen for this skill result.

  Architecture:
  - Mounted by AppSkillUseRenderer.ts when app_id='images' and skill_id='view'.
  - onFullscreen callback resolves the original image upload embed from EmbedStore
    and fires 'imagefullscreen' so ActiveChat mounts UploadedImageFullscreen.svelte.
  - Uses the shared imageEmbedCrypto cache so if the original ImageEmbedPreview
    already decrypted the image, we get it instantly from cache.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import {
    fetchAndDecryptImage,
    getCachedImageUrl,
    retainCachedImage,
    releaseCachedImage,
  } from './imageEmbedCrypto';

  /** Max display length for filename in the card title */
  const MAX_FILENAME_LENGTH = 30;

  interface Props {
    /** Unique embed ID for this skill-use embed */
    id: string;
    /** Original filename from the uploaded image embed (passed via decodedContent) */
    filename?: string;
    /** Processing status of the skill execution */
    status: 'processing' | 'finished' | 'error';
    /** Error message if skill failed */
    error?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /**
     * Called when the user clicks to open fullscreen.
     * Implemented by AppSkillUseRenderer: resolves original upload embed
     * and fires 'imagefullscreen' CustomEvent.
     */
    onFullscreen?: () => void;
    // --- Data from original image upload embed (resolved by AppSkillUseRenderer) ---
    /** S3 base URL from original image embed */
    s3BaseUrl?: string;
    /** S3 file variants from original image embed */
    s3Files?: Record<string, { s3_key: string; width: number; height: number; size_bytes: number; format: string }>;
    /** AES-256 key (base64) from original image embed */
    aesKey?: string;
    /** AES-GCM nonce (base64) from original image embed */
    aesNonce?: string;
  }

  let {
    id,
    filename,
    status: statusProp,
    error: errorProp,
    isMobile = false,
    onFullscreen,
    s3BaseUrl,
    s3Files,
    aesKey,
    aesNonce,
  }: Props = $props();

  // Local state for derived status
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localError = $state<string | undefined>(undefined);

  // Decrypted preview image blob URL
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);

  // Track retained S3 key for cache cleanup
  let retainedS3Key: string | undefined = undefined;

  // Lazy loading: only fetch when the embed scrolls into view
  let isInView = $state(false);
  let containerRef: HTMLElement | undefined = $state(undefined);
  let observer: IntersectionObserver | undefined = undefined;

  // Sync props to local state
  $effect(() => {
    localStatus = statusProp || 'processing';
    localError = errorProp;
  });

  // Set up IntersectionObserver for lazy loading (200px pre-fetch margin)
  $effect(() => {
    if (!containerRef) return;
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          isInView = true;
          observer?.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(containerRef);
    return () => observer?.disconnect();
  });

  onDestroy(() => {
    if (retainedS3Key) {
      releaseCachedImage(retainedS3Key);
      retainedS3Key = undefined;
    }
    observer?.disconnect();
  });

  // Derived state
  let status = $derived(localStatus);
  let error = $derived(localError);
  let previewS3Key = $derived(s3Files?.preview?.s3_key);

  /**
   * Card title: truncated filename or generic "Image" fallback.
   */
  let skillName = $derived.by(() => {
    if (!filename) return $text('app_skills.images.view');
    if (filename.length > MAX_FILENAME_LENGTH) {
      const lastDot = filename.lastIndexOf('.');
      if (lastDot > 0) {
        const ext = filename.slice(lastDot);
        const stem = filename.slice(0, lastDot);
        const allowedStem = MAX_FILENAME_LENGTH - ext.length - 1;
        return allowedStem > 0
          ? stem.slice(0, allowedStem) + '\u2026' + ext
          : filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
      }
      return filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
    }
    return filename;
  });

  /**
   * Card subtitle:
   * - processing → "Viewing…"
   * - finished   → empty (image fills the card)
   * - error      → error message
   */
  let statusText = $derived.by(() => {
    if (status === 'processing') return $text('app_skills.images.view.viewing');
    if (status === 'error') return error || '';
    return '';
  });

  /** Fullscreen enabled when finished and an image is available (or will load) */
  let isFullscreenEnabled = $derived(status === 'finished' && !!onFullscreen);

  /** Show image full-bleed when we have a decrypted URL and no error */
  let showFullWidthImage = $derived(!!imageUrl && !imageError && status === 'finished');

  /**
   * Load and decrypt the preview image from S3.
   * Uses the shared in-memory cache so ImageEmbedPreview cache hits are instant.
   */
  async function loadPreviewImage() {
    if (!previewS3Key || !s3BaseUrl || !aesKey || !aesNonce) {
      console.debug('[ImageViewEmbedPreview] Missing data for image load:', {
        hasPreviewKey: !!previewS3Key,
        hasS3BaseUrl: !!s3BaseUrl,
        hasAesKey: !!aesKey,
        hasAesNonce: !!aesNonce,
      });
      return;
    }

    if (imageUrl) return;

    // Check shared cache first (instant if ImageEmbedPreview already decrypted this)
    const cachedUrl = getCachedImageUrl(previewS3Key);
    if (cachedUrl) {
      imageUrl = cachedUrl;
      if (retainedS3Key && retainedS3Key !== previewS3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = previewS3Key;
      retainCachedImage(previewS3Key);
      return;
    }

    isLoadingImage = true;
    imageError = undefined;

    try {
      console.debug('[ImageViewEmbedPreview] Loading preview image from S3:', previewS3Key);
      const blob = await fetchAndDecryptImage(s3BaseUrl, previewS3Key, aesKey, aesNonce);
      imageUrl = URL.createObjectURL(blob);
      if (retainedS3Key && retainedS3Key !== previewS3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = previewS3Key;
      retainCachedImage(previewS3Key);
      console.debug('[ImageViewEmbedPreview] Preview image loaded successfully');
    } catch (err) {
      const errorDetail = err instanceof Error
        ? `${err.name}: ${err.message || '(no message)'}`
        : String(err);
      console.error('[ImageViewEmbedPreview] Failed to load preview image:', errorDetail);
      imageError = err instanceof Error
        ? (err.message || err.name || 'Failed to decrypt image')
        : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }

  // Auto-load image when finished, data is available, and embed is in view
  $effect(() => {
    if (
      isInView &&
      status === 'finished' &&
      previewS3Key &&
      s3BaseUrl &&
      aesKey &&
      aesNonce &&
      !imageUrl &&
      !isLoadingImage
    ) {
      loadPreviewImage();
    }
  });
</script>

<UnifiedEmbedPreview
  {id}
  appId="images"
  skillId="view"
  skillIconName="image"
  {status}
  {skillName}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  hasFullWidthImage={showFullWidthImage}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="image-view-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>

      {#if status === 'finished' && imageUrl && !imageError}
        <!-- Decrypted image — shown full-bleed -->
        <div class="image-content" class:clickable={isFullscreenEnabled}>
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
          <img
            src={imageUrl}
            alt={filename || 'Image'}
            class="preview-image"
            onclick={isFullscreenEnabled ? onFullscreen : undefined}
          />
        </div>

      {:else if status === 'finished' && imageError}
        <!-- Image decrypt failed -->
        <div class="image-error-small">
          <span class="error-icon-small">!</span>
          <span>{imageError}</span>
        </div>

      {:else if status === 'error'}
        <!-- Skill execution error -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{error || 'Image view failed'}</span>
        </div>

      {:else}
        <!-- Processing / loading skeleton -->
        <div class="skeleton-content">
          <div class="skeleton-lines">
            <div class="skeleton-line long"></div>
            <div class="skeleton-line short"></div>
          </div>
        </div>
      {/if}

    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .image-view-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  .image-view-preview.mobile {
    padding: 0;
  }

  /* Full-bleed image container */
  .image-content {
    width: 100%;
    height: 100%;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-10, #f5f5f5);
  }

  .image-content.clickable {
    cursor: zoom-in;
  }

  .image-content.clickable:hover .preview-image {
    opacity: 0.92;
  }

  .preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: opacity 0.15s ease;
  }

  /* Loading skeleton */
  .skeleton-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px 20px;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
  }

  .skeleton-lines {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .skeleton-line {
    height: 12px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-line.long { width: 80%; }
  .skeleton-line.short { width: 50%; }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  /* Inline image error */
  .image-error-small {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 12px;
    font-size: 11px;
    color: var(--color-grey-50, #888);
  }

  .error-icon-small {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--color-error-20, #f5c0c0);
    color: var(--color-error-70, #b04a4a);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 700;
    flex-shrink: 0;
  }

  /* Skill execution error */
  .error-state {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    background: var(--color-error-5, #fff5f5);
    border-radius: 6px;
    margin: 12px;
  }

  .error-icon {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--color-error-20, #f5c0c0);
    color: var(--color-error-70, #b04a4a);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 700;
    flex-shrink: 0;
  }

  .error-text {
    font-size: 13px;
    color: var(--color-error-70, #b04a4a);
    line-height: 1.4;
  }

  /* Dark mode */
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }

  :global(.dark) .image-content {
    background: var(--color-grey-90, #1a1a1a);
  }

  :global(.dark) .error-state {
    background: var(--color-error-95, #2a1515);
  }

  :global(.dark) .error-text {
    color: var(--color-error-40, #d07a7a);
  }
</style>
