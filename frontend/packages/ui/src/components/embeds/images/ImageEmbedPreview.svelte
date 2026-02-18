<!--
  frontend/packages/ui/src/components/embeds/images/ImageEmbedPreview.svelte

  Preview component for user-uploaded image embeds in read-only message display.

  Rendered by ImageRenderer.ts when the image embed has S3 data but no local
  blob URL (i.e. the message has been serialized/received and the ephemeral blob
  URL from the upload session is gone).

  Shows:
  - Finished (loading): skeleton while the image decrypts from S3
  - Finished (loaded): decrypted preview image, clickable for fullscreen
  - Uploading: skeleton with "Uploading…" label (shouldn't normally appear here)
  - Error: error state card

  Fullscreen: calls onFullscreen() callback → ImageRenderer.ts fires 'imagefullscreen'
  CustomEvent → ActiveChat.svelte mounts UploadedImageFullscreen.svelte.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';

  /**
   * S3 file variant metadata for a single image.
   * Matches the shape set by _performUpload() in embedHandlers.ts.
   */
  interface S3FileVariant {
    s3_key: string;
    width: number;
    height: number;
    size_bytes: number;
    format: string;
  }

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Original filename of the uploaded image */
    filename?: string;
    /** Upload/embed status */
    status: 'uploading' | 'processing' | 'finished' | 'error';
    /** S3 file variants: { preview, full, original } — each with s3_key + dims */
    s3Files?: Record<string, S3FileVariant>;
    /** S3 base URL for constructing full image URLs */
    s3BaseUrl?: string;
    /** Plaintext AES-256 key (base64) for client-side decryption */
    aesKey?: string;
    /** AES-GCM nonce (base64) shared across encrypted variants */
    aesNonce?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Called when the user clicks to open fullscreen view */
    onFullscreen?: () => void;
  }

  let {
    id,
    filename,
    status: statusProp,
    s3Files,
    s3BaseUrl,
    aesKey,
    aesNonce,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  // Decrypted image blob URL (set after successful S3 fetch+decrypt)
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);

  // Track which S3 key we retained so we can release on unmount
  let retainedS3Key: string | undefined = undefined;

  // Lazy loading: only fetch when the embed scrolls into view
  let isInView = $state(false);
  let containerRef: HTMLElement | undefined = $state(undefined);
  let observer: IntersectionObserver | undefined = undefined;

  // Set up IntersectionObserver for lazy loading.
  // Start loading 200px before the embed enters the viewport to avoid visible pop-in.
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

  // Release cached blob URL reference on component unmount to avoid memory leaks.
  onDestroy(() => {
    if (retainedS3Key) {
      releaseCachedImage(retainedS3Key);
      retainedS3Key = undefined;
    }
    observer?.disconnect();
  });

  // Derived values
  let status = $derived(statusProp);
  let previewS3Key = $derived(s3Files?.preview?.s3_key);

  // Map our status to the UnifiedEmbedPreview status union ('uploading' → 'processing')
  let unifiedStatus = $derived(
    status === 'uploading' ? 'processing' : status as 'processing' | 'finished' | 'error',
  );

  /**
   * Fetch and decrypt the preview image from S3.
   * Uses the shared in-memory cache to avoid redundant network+crypto work.
   */
  async function loadPreviewImage() {
    if (!previewS3Key || !s3BaseUrl || !aesKey || !aesNonce) {
      console.debug('[ImageEmbedPreview] Missing data for image load:', {
        hasPreviewKey: !!previewS3Key,
        hasS3BaseUrl: !!s3BaseUrl,
        hasAesKey: !!aesKey,
        hasAesNonce: !!aesNonce,
      });
      return;
    }

    // Don't reload if we already have the image URL
    if (imageUrl) return;

    // Check shared cache first — instant hit if another component already decrypted this
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
      console.debug('[ImageEmbedPreview] Loading preview image from S3:', previewS3Key);
      const blob = await fetchAndDecryptImage(s3BaseUrl, previewS3Key, aesKey, aesNonce);
      imageUrl = URL.createObjectURL(blob);
      if (retainedS3Key && retainedS3Key !== previewS3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = previewS3Key;
      retainCachedImage(previewS3Key);
      console.debug('[ImageEmbedPreview] Preview image loaded successfully');
    } catch (err) {
      const errorDetail = err instanceof Error
        ? `${err.name}: ${err.message || '(no message)'}`
        : String(err);
      console.error('[ImageEmbedPreview] Failed to load preview image:', errorDetail);
      imageError = err instanceof Error
        ? (err.message || err.name || 'Failed to decrypt image')
        : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }

  // Load image when the embed enters the viewport and S3 data is available.
  $effect(() => {
    if (isInView && status === 'finished' && previewS3Key && s3BaseUrl && aesKey && aesNonce && !imageUrl && !isLoadingImage) {
      loadPreviewImage();
    }
  });
</script>

<UnifiedEmbedPreview
  {id}
  appId="images"
  skillId="view"
  skillIconName="ai"
  status={unifiedStatus}
  skillName={$text('app_skills.images.view.text')}
  {isMobile}
  {onFullscreen}
  showStatus={status !== 'finished' || !imageUrl}
  showSkillIcon={true}
  hasFullWidthImage={status === 'finished' && !!imageUrl && !imageError}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="image-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>
      {#if status === 'finished' && imageUrl && !imageError}
        <!-- Finished: show the decrypted image, clickable for fullscreen -->
        <div class="image-content">
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
          <img
            src={imageUrl}
            alt={filename || 'Uploaded image'}
            class="preview-image"
            onclick={onFullscreen}
          />
        </div>
      {:else if status === 'finished' && imageError}
        <!-- Image decryption failed -->
        <div class="image-error-small">
          <span class="error-icon-small">!</span>
          <span>{imageError}</span>
        </div>
      {:else if status === 'error'}
        <!-- Upload/embed error state -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{$text('app_skills.images.view.text')}</span>
        </div>
      {:else}
        <!-- Loading / uploading: show skeleton -->
        <div class="skeleton-content">
          {#if filename}
            <span class="filename-text">{filename}</span>
          {/if}
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
  .image-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  .image-preview.mobile {
    padding: 0;
  }

  /* Finished state: full-bleed image */
  .image-content {
    width: 100%;
    height: 100%;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-10, #f5f5f5);
    cursor: zoom-in;
  }

  .preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: opacity 0.15s ease;
  }

  .image-content:hover .preview-image {
    opacity: 0.92;
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

  .filename-text {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-60, #777);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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

  .skeleton-line.long {
    width: 80%;
  }

  .skeleton-line.short {
    width: 50%;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  /* Image decrypt error (small, inline) */
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

  /* Upload/embed error state */
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
