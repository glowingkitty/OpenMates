<!--
  frontend/packages/ui/src/components/embeds/images/ImageEmbedPreview.svelte

  Preview card for user-uploaded image embeds.

  Modelled after CodeEmbedPreview.svelte:
  - No AI/skill icon (showSkillIcon=false)
  - skillName = truncated filename (title line of the card)
  - customStatusText = dynamic subtitle ("Uploading…", "Upload failed", or empty)
  - Image shown full-bleed in the details snippet, no overlay on the image itself

  Covers two rendering contexts:

  A) Editor context (src prop set — local blob URL from upload session):
     - status 'uploading': image shown + "Uploading…" subtitle
     - status 'error': image shown + "Upload failed" subtitle
     - status 'finished' (no S3): image shown, no subtitle (demo / unauthenticated)
     - status 'finished' (S3 present): image shown, fullscreen enabled

  B) Read-only context (src absent, S3 data present — received/sent message):
     - Lazy-loads and decrypts the preview image from S3 using AES-256-GCM.
     - Shows skeleton while loading, decrypted image once ready.

  Fullscreen: calls onFullscreen() → ImageRenderer.ts fires 'imagefullscreen'
  CustomEvent → ActiveChat.svelte mounts UploadedImageFullscreen.svelte.

  Stop button: calls onStop() → embedHandlers.cancelUpload(id) aborts the
  in-flight fetch; the caller (ImageRenderer.ts) supplies this callback.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';
  import { skillPreviewService } from '../../../services/skillPreviewService';

  /** Max display length for the filename in the card title (chars) */
  const MAX_FILENAME_LENGTH = 30;

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
    /** Whether the user is authenticated (affects subtitle text) */
    isAuthenticated?: boolean;
    /** File size in bytes (from the original File object) */
    fileSize?: number;
    /** File MIME type (from the original File object, e.g. 'image/jpeg') */
    fileType?: string;
    /** Called when the user clicks to open fullscreen view */
    onFullscreen?: () => void;
    /**
     * Called when the user clicks the stop button.
     * The caller (ImageRenderer.ts) wires this to cancelUpload(id).
     */
    onStop?: () => void;
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
    isAuthenticated = true,
    fileSize,
    fileType,
    onFullscreen,
    onStop,
  }: Props = $props();

  // Decrypted image blob URL (set after successful S3 fetch+decrypt)
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);

  /**
   * When the images.view skill is executing, show "Viewing…" status on this embed.
   * Set to true when a skill_execution_status event with app_id="images", skill_id="view",
   * status="processing", and preview_data.embed_id matching our id is received.
   * Reset to false when skill finishes or errors.
   */
  let isBeingViewed = $state(false);

  // Subscribe to skill preview updates to show "Viewing…" state while images.view runs
  function handleSkillPreviewUpdate(event: Event): void {
    const customEvent = event as CustomEvent;
    const { previewData } = customEvent.detail || {};
    if (!previewData) return;
    // Only react to images.view skill events for our embed
    if (previewData.app_id !== 'images' || previewData.skill_id !== 'view') return;
    const embedId = (previewData as Record<string, unknown>).embed_id as string | undefined;
    if (embedId && embedId !== id) return;
    // Set viewing state based on skill status
    if (previewData.status === 'processing') {
      isBeingViewed = true;
    } else {
      // finished or error — revert to normal
      isBeingViewed = false;
    }
  }

  skillPreviewService.addEventListener('skillPreviewUpdate', handleSkillPreviewUpdate);

  // Portrait detection: detected after the image loads naturally.
  // For portrait images (height > width) we expand the embed card height so the
  // full image is visible instead of being cropped by object-fit: cover.
  let isPortrait = $state(false);
  // Card height override in pixels (undefined → default 200px from UnifiedEmbedPreview)
  let portraitCardHeight = $state<number | undefined>(undefined);

  /** Max embed card height for portrait images (px). Keeps them from being too tall. */
  const MAX_PORTRAIT_CARD_HEIGHT = 400;
  /** Default card height (must match UnifiedEmbedPreview desktop height). */
  const DEFAULT_CARD_HEIGHT = 200;

  /**
   * Called when the preview <img> finishes loading.
   * Detects portrait images and calculates a proportional card height so the
   * full image height fits without cropping.
   */
  function handleImageLoad(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    const { naturalWidth, naturalHeight } = img;
    if (!naturalWidth || !naturalHeight) return;

    if (naturalHeight > naturalWidth) {
      // Portrait image: compute the height that fits the full image within the 300px wide card.
      // ratio = naturalHeight / naturalWidth  →  needed px height = 300 * ratio
      const neededHeight = Math.round((DEFAULT_CARD_HEIGHT * naturalHeight) / naturalWidth);
      isPortrait = true;
      portraitCardHeight = Math.min(neededHeight, MAX_PORTRAIT_CARD_HEIGHT);
    } else {
      isPortrait = false;
      portraitCardHeight = undefined;
    }
  }

  // Track which S3 key we retained so we can release on unmount
  let retainedS3Key: string | undefined = undefined;

  // Lazy loading: only fetch when the embed scrolls into view (S3 path only)
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
    // Unsubscribe from skill preview updates
    skillPreviewService.removeEventListener('skillPreviewUpdate', handleSkillPreviewUpdate);
  });

  // --- Derived state ---

  let status = $derived(statusProp);
  let previewS3Key = $derived(s3Files?.preview?.s3_key);

  /** Map our upload-specific status to the UnifiedEmbedPreview status union.
   *  When being viewed by the AI (isBeingViewed), show the processing spinner. */
  let unifiedStatus = $derived(
    isBeingViewed ? 'processing'
    : status === 'uploading' ? 'processing'
    : status as 'processing' | 'finished' | 'error',
  );

  /** Whether we have a local blob URL (editor context) */
  let hasSrcBlob = $derived(!!src);

  /** The URL to display in the <img> — local blob takes precedence over decrypted S3 */
  let displayUrl = $derived(src ?? imageUrl);

  /** Fullscreen is enabled once an image is available and the upload is done */
  let isFullscreenEnabled = $derived(
    status === 'finished' && !!displayUrl && !imageError,
  );

  /**
   * Card title: truncated filename.
   * Falls back to the generic "Image" label if no filename is set.
   */
  let skillName = $derived.by(() => {
    if (!filename) return $text('app_skills.images.view');
    if (filename.length > MAX_FILENAME_LENGTH) {
      // Keep the extension visible: truncate the stem and re-attach the extension
      const lastDot = filename.lastIndexOf('.');
      if (lastDot > 0) {
        const ext = filename.slice(lastDot); // e.g. ".jpg"
        const stem = filename.slice(0, lastDot);
        const allowedStem = MAX_FILENAME_LENGTH - ext.length - 1; // -1 for the '…'
        return allowedStem > 0
          ? stem.slice(0, allowedStem) + '\u2026' + ext
          : filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
      }
      return filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
    }
    return filename;
  });

  /**
   * Format a file size in bytes into a human-readable string (e.g. "1.2 MB").
   */
  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  /**
   * Derive file type label from MIME type or filename extension.
   * Returns an uppercase short label like "JPEG", "PNG", "WEBP", etc.
   */
  function getFileTypeLabel(mimeType?: string, fname?: string): string {
    // Try MIME type first (e.g. 'image/jpeg' → 'JPEG')
    if (mimeType) {
      const sub = mimeType.split('/')[1];
      if (sub) {
        // Normalise common MIME subtypes to friendlier labels
        const normalised = sub.replace(/^x-/, '').toUpperCase();
        if (normalised === 'SVG+XML') return 'SVG';
        return normalised;
      }
    }
    // Fallback: extract extension from filename
    if (fname) {
      const lastDot = fname.lastIndexOf('.');
      if (lastDot > 0) return fname.slice(lastDot + 1).toUpperCase();
    }
    return '';
  }

  /**
   * Card subtitle (customStatusText):
   * - 'uploading'                       → "Uploading…"
   * - 'error'                           → "Upload failed" (or server error message)
   * - 'finished' + !isAuthenticated     → "Signup to upload…"
   * - 'finished' + isAuthenticated      → "JPEG · 1.2 MB" (file type + size)
   * - no displayUrl yet (S3 loading)    → empty (UnifiedEmbedPreview shows its own skeleton)
   */
  let statusText = $derived.by(() => {
    // When the AI is actively viewing this image, show "Viewing…" regardless of upload status
    if (isBeingViewed) return $text('app_skills.images.view.viewing');
    if (status === 'uploading') return $text('app_skills.images.view.uploading');
    if (status === 'error') return uploadError || $text('app_skills.images.view.upload_failed');
    if (imageError) return imageError;
    if (status === 'finished') {
      // Unauthenticated users: prompt to sign up for actual upload
      if (!isAuthenticated) {
        return $text('app_skills.images.view.signup_to_upload');
      }
      // Authenticated + finished: show file type and size
      const typeLabel = getFileTypeLabel(fileType, filename);
      const sizeLabel = fileSize ? formatFileSize(fileSize) : '';
      if (typeLabel && sizeLabel) return `${typeLabel} \u00B7 ${sizeLabel}`;
      if (typeLabel) return typeLabel;
      if (sizeLabel) return sizeLabel;
      // Fallback: show "Uploaded image" (the description key)
      return $text('app_skills.images.view.description');
    }
    return '';
  });

  /**
   * Whether the stop button should be shown.
   * Only during active upload (editor context).
   */
  let showStop = $derived(hasSrcBlob && status === 'uploading' && !!onStop);

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
  skillIconName="image"
  status={unifiedStatus}
  {skillName}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  onStop={showStop ? onStop : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  hasFullWidthImage={!!displayUrl && !imageError && status !== 'error'}
  customHeight={isPortrait ? portraitCardHeight : undefined}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="image-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>

      {#if displayUrl && !imageError}
        <!--
          Image available (local blob or decrypted S3).
          Shown full-bleed with no overlay — status is communicated via the
          card's subtitle (customStatusText), not drawn on top of the image.
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
            class:portrait={isPortrait}
            onload={handleImageLoad}
            onclick={isFullscreenEnabled ? onFullscreen : undefined}
          />
        </div>

      {:else if imageError}
        <!-- S3 decryption failed (read-only context) -->
        <div class="image-error-small">
          <span class="error-icon-small">!</span>
          <span>{imageError}</span>
        </div>

      {:else}
        <!-- No image yet: skeleton placeholder (S3 loading, or status 'error' without blob) -->
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

  .preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: opacity 0.15s ease;
  }

  /*
   * Portrait (vertical) images: use object-fit: contain so the full image
   * height is visible without cropping. The card height is dynamically
   * expanded via the customHeight prop on UnifiedEmbedPreview.
   */
  .preview-image.portrait {
    object-fit: contain;
    background: var(--color-grey-15, #f0f0f0);
  }

  .image-content.clickable:hover .preview-image {
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

  /* Dark mode */
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }

  :global(.dark) .image-content {
    background: var(--color-grey-90, #1a1a1a);
  }
</style>
