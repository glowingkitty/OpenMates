<!--
  frontend/packages/ui/src/components/embeds/images/ImageEmbedPreview.svelte

  Preview component for user-uploaded image embeds.

  Covers two rendering contexts:

  A) Editor context (src prop set — local blob URL from upload session):
     - status 'uploading': image at reduced opacity + spinner overlay
     - status 'error': image at reduced opacity + error overlay
     - status 'finished' (no S3 data): full-opacity image (demo / unauthenticated)
     - status 'finished' (S3 data present): full-opacity image + fullscreen enabled

  B) Read-only context (src absent, S3 data present — received/sent message):
     - Lazy-loads and decrypts the preview image from S3 using AES-256-GCM.
     - Shows skeleton while loading, decrypted image once ready.

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
    /**
     * Local blob URL for instant preview while uploading (editor context only).
     * When set, the image is displayed directly without any S3 fetch.
     * Not present in read-only message display (blob URLs are ephemeral).
     */
    src?: string;
    /** Error message to display when status is 'error' */
    uploadError?: string;
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
    src,
    uploadError,
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

  // In editor context (src set): image is ready to show directly from the blob URL.
  // Fullscreen is enabled once upload finishes (S3 data available).
  let hasSrcBlob = $derived(!!src);
  let isUploading = $derived(status === 'uploading');
  let isError = $derived(status === 'error');

  // Display image when:
  //   - We have a local blob URL (editor context), OR
  //   - We have successfully decrypted an S3 image (read-only context)
  let displayUrl = $derived(src ?? imageUrl);

  // Fullscreen is enabled when upload is done and S3 data is present, OR
  // in read-only mode when the S3 image has been decrypted.
  let isFullscreenEnabled = $derived(
    status === 'finished' && !!displayUrl && !imageError,
  );

  // Whether to show the upload spinner overlay (editor context only)
  let showSpinner = $derived(hasSrcBlob && isUploading);

  // Whether to show the error overlay (editor context, upload failed)
  let showErrorOverlay = $derived(hasSrcBlob && isError);

  // Image opacity: dim while uploading
  let imageOpacity = $derived(isUploading ? 0.45 : 1);

  /**
   * Fetch and decrypt the preview image from S3.
   * Uses the shared in-memory cache to avoid redundant network+crypto work.
   * Only called in read-only context (src is absent).
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

  // Load image from S3 when in read-only context (no local blob URL).
  // Triggered lazily once the embed scrolls into view.
  $effect(() => {
    if (!src && isInView && status === 'finished' && previewS3Key && s3BaseUrl && aesKey && aesNonce && !imageUrl && !isLoadingImage) {
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
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  showStatus={!displayUrl || isUploading || isError}
  showSkillIcon={true}
  hasFullWidthImage={!!displayUrl && !isError && !imageError}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="image-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>

      {#if displayUrl && !imageError}
        <!--
          Image available (either local blob or decrypted S3 URL).
          In editor context: may be dimmed with an overlay while uploading/errored.
          In read-only context: always shown at full opacity.
        -->
        <div
          class="image-content"
          class:clickable={isFullscreenEnabled}
        >
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
          <img
            src={displayUrl}
            alt={filename || 'Uploaded image'}
            class="preview-image"
            style:opacity={imageOpacity}
            onclick={isFullscreenEnabled ? onFullscreen : undefined}
          />

          {#if showSpinner}
            <!-- Uploading overlay: spinner + label -->
            <div class="img-overlay">
              <div class="img-spinner"></div>
              <span class="img-overlay-label">Uploading&hellip;</span>
            </div>
          {:else if showErrorOverlay}
            <!-- Error overlay: icon + message -->
            <div class="img-overlay img-overlay--error">
              <span class="img-overlay-icon">!</span>
              <span class="img-overlay-label">{uploadError || 'Upload failed'}</span>
            </div>
          {/if}
        </div>

      {:else if status === 'finished' && imageError}
        <!-- S3 decryption failed (read-only context) -->
        <div class="image-error-small">
          <span class="error-icon-small">!</span>
          <span>{imageError}</span>
        </div>

      {:else if status === 'error' && !hasSrcBlob}
        <!-- Upload/embed error with no blob to show -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{uploadError || $text('app_skills.images.view.text')}</span>
        </div>

      {:else}
        <!-- Loading / uploading without a blob preview: show skeleton -->
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

  /* Image content wrapper */
  .image-content {
    position: relative;
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

  .preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: opacity 0.2s ease;
  }

  .image-content.clickable:hover .preview-image {
    opacity: 0.92;
  }

  /* Upload/error overlay (editor context, shown above the dimmed preview image) */
  .img-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    pointer-events: none;
  }

  .img-spinner {
    width: 26px;
    height: 26px;
    border: 3px solid rgba(255, 255, 255, 0.4);
    border-top-color: #fff;
    border-radius: 50%;
    animation: img-spin 0.75s linear infinite;
  }

  @keyframes img-spin {
    to { transform: rotate(360deg); }
  }

  .img-overlay-label {
    font-size: 0.72rem;
    font-weight: 500;
    color: #fff;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
    letter-spacing: 0.02em;
  }

  .img-overlay-icon {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: rgba(220, 38, 38, 0.85);
    color: #fff;
    font-size: 1rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }

  .img-overlay--error .img-overlay-label {
    color: rgba(255, 220, 220, 0.95);
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
