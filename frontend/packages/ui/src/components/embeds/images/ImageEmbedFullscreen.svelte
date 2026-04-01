<!--
  frontend/packages/ui/src/components/embeds/images/ImageEmbedFullscreen.svelte

  Fullscreen viewer for user-uploaded image embeds.

  Shows:
  - Full-resolution decrypted image from S3 (progressive: preview first, then full)
    OR a local blob URL as fallback when the user is not authenticated (no S3 upload).
  - Download button for the original file (S3 path only)
  - Close button (inherited from UnifiedEmbedFullscreen)
  - Embed header with truncated filename + "Signup to upload…" or file type/size subtitle

  Does NOT show prompt/model info — uploaded images are user photos, not AI-generated.

  Props mirror the files/aesKey/aesNonce structure returned by the uploads microservice,
  which matches the generate_task.py structure so the same imageEmbedCrypto utilities work.

  Fullscreen: mounted by ActiveChat.svelte when 'imagefullscreen' CustomEvent is received
  (fired by ImageRenderer.ts → ImageEmbedPreview.svelte → onFullscreen()).
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';
  import { text } from '@repo/ui';

  /** Max display length for the filename in the embed header title (chars) */
  const MAX_FILENAME_LENGTH = 30;

  /**
   * Props for uploaded image fullscreen viewer.
   */
  interface Props {
    /** S3 base URL for image files (from upload response s3_base_url) */
    s3BaseUrl?: string;
    /** Files metadata from embed content — original, full, preview variants */
    files?: {
      preview?: { s3_key: string; width: number; height: number; format: string };
      full?: { s3_key: string; width: number; height: number; format: string };
      original?: { s3_key: string; width: number; height: number; format: string };
    };
    /** AES-256 key (base64) for decrypting S3 files */
    aesKey?: string;
    /** AES-GCM nonce (base64) shared across all encrypted variants */
    aesNonce?: string;
    /** Original filename for display and download */
    filename?: string;
    /**
     * Local blob URL (from the editor embed).
     * Used as an instant fallback when S3 data is unavailable (unauthenticated users).
     * This avoids the infinite loading spinner for users who haven't signed up.
     */
    src?: string;
    /** Whether the user is authenticated (controls subtitle text in the info bar) */
    isAuthenticated?: boolean;
    /** File size in bytes (from the original File object) — shown in header subtitle */
    fileSize?: number;
    /** File MIME type (e.g. 'image/jpeg') — shown in header subtitle */
    fileType?: string;
    /** Close handler */
    onClose: () => void;
    /**
     * AI detection metadata from SightEngine (set after upload by the server pipeline).
     * Shape: { ai_generated: number (0–1), provider: string } | null
     * The AI generated badge is only shown when ai_generated > 0.7.
     */
    aiDetection?: { ai_generated: number; provider: string } | null;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of the navigation that triggered this mount (for slide animation) */
    navigateDirection?: 'next' | 'previous' | null;
    /** Whether to show the "chat" button to restore chat visibility */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }

  let {
    s3BaseUrl,
    files,
    aesKey,
    aesNonce,
    filename = 'image',
    src,
    isAuthenticated = true,
    fileSize,
    fileType,
    onClose,
    aiDetection = null,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection = null,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  /** Threshold matching the backend's "LIKELY AI-GENERATED" log in upload_route.py */
  const AI_GENERATED_THRESHOLD = 0.7;

  /** Show the AI generated badge only when SightEngine score exceeds the threshold */
  let showAiBadge = $derived(
    !!aiDetection && aiDetection.ai_generated > AI_GENERATED_THRESHOLD,
  );

  // -------------------------------------------------------------------------
  // Image loading state
  // Progressive loading: show cached preview instantly while full-res loads.
  // -------------------------------------------------------------------------

  /** Max number of times to attempt loading the full image before giving up. */
  const MAX_FULL_IMAGE_RETRIES = 3;

  let previewImageUrl = $state<string | undefined>(undefined);
  let fullImageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  let isDownloading = $state(false);
  /** How many times we have attempted to load the full image. */
  let loadRetryCount = $state(0);

  // Track retained S3 keys so we release LRU cache references on unmount
  let retainedPreviewKey: string | undefined = undefined;
  let retainedFullKey: string | undefined = undefined;

  // -------------------------------------------------------------------------
  // Header: truncated filename + subtitle
  // -------------------------------------------------------------------------

  /**
   * Truncate filename to MAX_FILENAME_LENGTH characters, keeping the extension
   * visible if present (mirrors the logic in ImageEmbedPreview.svelte).
   */
  let headerTitle = $derived.by(() => {
    if (!filename || filename === 'image') return $text('app_skills.images.view');
    if (filename.length <= MAX_FILENAME_LENGTH) return filename;
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
    if (mimeType) {
      const sub = mimeType.split('/')[1];
      if (sub) {
        const normalised = sub.replace(/^x-/, '').toUpperCase();
        if (normalised === 'SVG+XML') return 'SVG';
        return normalised;
      }
    }
    if (fname) {
      const lastDot = fname.lastIndexOf('.');
      if (lastDot > 0) return fname.slice(lastDot + 1).toUpperCase();
    }
    return '';
  }

  /**
   * Header subtitle:
   * - Unauthenticated: "Signup to upload…"
   * - Authenticated: "JPEG · 1.2 MB" (or just type or just size)
   */
  let headerSubtitle = $derived.by(() => {
    if (!isAuthenticated) {
      return $text('app_skills.images.view.signup_to_upload');
    }
    const typeLabel = getFileTypeLabel(fileType, filename);
    const sizeLabel = fileSize ? formatFileSize(fileSize) : '';
    if (typeLabel && sizeLabel) return `${typeLabel} \u00B7 ${sizeLabel}`;
    if (typeLabel) return typeLabel;
    if (sizeLabel) return sizeLabel;
    return $text('app_skills.images.view.description');
  });

  // -------------------------------------------------------------------------
  // Image loading: S3 path (authenticated) + blob fallback (unauthenticated)
  // -------------------------------------------------------------------------

  /**
   * Load the full-resolution image from S3 with progressive enhancement.
   * Only called when S3 data (s3BaseUrl, aesKey, aesNonce) is present.
   * The blob-URL fallback for unauthenticated users is handled directly in
   * the $effect below, so that Svelte 5 can track `src` as a dependency.
   *
   * S3 path:
   *   1. Show the cached preview immediately for zero-latency progressive display.
   *   2. Fetch + decrypt the full-resolution variant in the background.
   *   3. Swap to full-res when ready.
   */
  async function loadFullImage() {
    if (fullImageUrl) return;
    if (!s3BaseUrl || !aesKey || !aesNonce) return; // guard — caller should check

    // Prevent infinite retry loops — give up after MAX_FULL_IMAGE_RETRIES attempts
    if (loadRetryCount >= MAX_FULL_IMAGE_RETRIES) {
      console.warn(
        `[ImageEmbedFullscreen] Giving up after ${MAX_FULL_IMAGE_RETRIES} failed attempts`,
      );
      return;
    }

    // --- S3 path: progressive load ---

    // Step 1: Show cached preview instantly for progressive loading
    const previewKey = files?.preview?.s3_key;
    if (previewKey && !previewImageUrl) {
      const cachedPreview = getCachedImageUrl(previewKey);
      if (cachedPreview) {
        previewImageUrl = cachedPreview;
        retainedPreviewKey = previewKey;
        retainCachedImage(previewKey);
      }
    }

    // Step 2: Load the full-res variant (prefer 'full', fall back to 'preview')
    const fullFileData = files?.full || files?.preview;
    if (!fullFileData?.s3_key) return;

    // Check LRU cache first — avoids redundant S3 fetches
    const cachedFull = getCachedImageUrl(fullFileData.s3_key);
    if (cachedFull) {
      fullImageUrl = cachedFull;
      retainedFullKey = fullFileData.s3_key;
      retainCachedImage(fullFileData.s3_key);
      return;
    }

    loadRetryCount += 1;
    isLoadingImage = true;
    imageError = undefined;

    try {
      console.debug(
        `[ImageEmbedFullscreen] Loading full image from S3 (attempt ${loadRetryCount}/${MAX_FULL_IMAGE_RETRIES}):`,
        fullFileData.s3_key,
      );
      const blob = await fetchAndDecryptImage(s3BaseUrl, fullFileData.s3_key, aesKey, aesNonce);
      fullImageUrl = URL.createObjectURL(blob);
      retainedFullKey = fullFileData.s3_key;
      retainCachedImage(fullFileData.s3_key);
    } catch (err) {
      // DOMException (from crypto.subtle.decrypt) serialises as {} with console.error —
      // extract the message explicitly so we get a meaningful error in the console.
      const errMsg =
        err instanceof DOMException
          ? `DOMException(${err.name}): ${err.message || 'decryption failed'}`
          : err instanceof Error
            ? err.message
            : String(err);
      console.error(
        `[ImageEmbedFullscreen] Failed to load full image (attempt ${loadRetryCount}/${MAX_FULL_IMAGE_RETRIES}):`,
        errMsg,
        err,
      );
      imageError = errMsg || 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }

  // Auto-load image on mount.
  // We also read src/s3BaseUrl/aesKey/aesNonce inside the effect so Svelte 5
  // tracks them as reactive dependencies and re-runs if they change.
  $effect(() => {
    // Declare local refs to the props we care about — Svelte 5 tracks
    // all reactive reads inside $effect regardless of how they're used.
    const currentSrc = src;
    const currentS3 = s3BaseUrl;
    const currentKey = aesKey;
    const currentNonce = aesNonce;

    if (!fullImageUrl && !isLoadingImage && !imageError) {
      // Use the locally-read values so the compiler knows they're dependencies.
      if (!currentS3 || !currentKey || !currentNonce) {
        // Blob path: use local src when S3 is not available
        if (currentSrc) {
          fullImageUrl = currentSrc;
          console.debug('[ImageEmbedFullscreen] Using local blob URL (no S3 data available)');
        }
      } else {
        // S3 path: async load
        loadFullImage();
      }
    }
  });

  // Release LRU cache references on unmount to avoid memory leaks
  onDestroy(() => {
    if (retainedPreviewKey) releaseCachedImage(retainedPreviewKey);
    if (retainedFullKey) releaseCachedImage(retainedFullKey);
  });

  /**
   * Download the original file by decrypting it from S3 and triggering a
   * browser download with the original filename.
   * Only available when S3 data is present (authenticated users).
   */
  async function handleDownload() {
    if (!files?.original?.s3_key || !s3BaseUrl || !aesKey || !aesNonce) return;
    if (isDownloading) return;

    isDownloading = true;
    try {
      const blob = await fetchAndDecryptImage(s3BaseUrl, files.original.s3_key, aesKey, aesNonce);
      const ext = files.original.format || 'bin';
      // Use the original filename if it already has an extension, otherwise append
      const downloadName = filename.includes('.') ? filename : `${filename}.${ext}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('[ImageEmbedFullscreen] Failed to download original:', err);
    } finally {
      isDownloading = false;
    }
  }

  /**
   * Open the full-size image in a new browser tab on click.
   * Middle-click and Ctrl/Cmd+click use the native link behaviour.
   */
  async function handleImageClick(e: MouseEvent) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    if (fullImageUrl) {
      window.open(fullImageUrl, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="images"
  skillId="view"
  skillIconName="image"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}

  showShare={!!files?.original}
  {onClose}
  onDownload={files?.original ? handleDownload : undefined}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="image-embed-fullscreen" data-testid="image-embed-fullscreen">
      {#if imageError}
        <div class="error-container">
          <div class="error-icon">!</div>
          <p class="error-message">{imageError}</p>
        </div>
      {:else if fullImageUrl}
        <div class="image-wrapper">
          <!-- Clicking opens original in new tab; Ctrl/Cmd+click uses native link -->
          <a href={fullImageUrl} target="_blank" rel="noopener noreferrer" class="image-link" onclick={handleImageClick}>
            <img src={fullImageUrl} alt={filename} class="full-image" />
          </a>
          {#if showAiBadge}
            <!-- AI generated badge: shown only when SightEngine confirms ai_generated > 0.7 -->
            <div class="ai-badge" aria-label={$text('app_skills.images.view.ai_generated')}>
              <span class="ai-badge-icon"></span>
              <span class="ai-badge-label">{$text('app_skills.images.view.ai_generated')}</span>
            </div>
          {/if}
        </div>
      {:else if previewImageUrl && isLoadingImage}
        <!-- Progressive: show blurred preview while full-res fetches -->
        <div class="image-wrapper progressive">
          <img src={previewImageUrl} alt={filename} class="full-image preview-placeholder" />
          <div class="progressive-overlay">
            <div class="loading-spinner small"></div>
          </div>
        </div>
      {:else}
        <!-- Loading state (S3 fetch in progress, or waiting for effect to fire) -->
        <div class="image-loading" data-testid="image-loading">
          <div class="loading-spinner"></div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /*
   * Main container: sits in normal document flow, below the EmbedHeader banner.
   * Uses min-height so it fills the visible space below the header without
   * needing position: absolute (which caused the image to overlap the header).
   *
   * The fullscreen panel is typically ~80vh tall.  EmbedHeader is ~160px.
   * min-height: calc(100vh - 220px) ensures the centering context is tall enough
   * even at small viewport heights, while still scrolling gracefully if the
   * viewport is tiny.
   */
  .image-embed-fullscreen {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: calc(100vh - 220px);
    padding: 24px;
    box-sizing: border-box;
  }

  /* ==========================================================================
     Image wrapper + link
     ========================================================================== */

  .image-wrapper {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    max-width: 100%;
  }

  /* AI generated badge: pill shown when SightEngine confirms image is AI-generated */
  .ai-badge {
    position: absolute;
    top: 12px;
    right: 12px;
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px 5px 8px;
    border-radius: 20px;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(4px);
    pointer-events: none;
    flex-shrink: 0;
  }

  .ai-badge-icon {
    display: block;
    flex-shrink: 0;
    width: 14px;
    height: 14px;
    background: #ffffff;
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .ai-badge-label {
    font-size: 12px;
    font-weight: 600;
    color: #ffffff;
    line-height: 1;
    white-space: nowrap;
    letter-spacing: 0.01em;
  }

  .image-link {
    display: flex;
    align-items: center;
    justify-content: center;
    max-width: 100%;
    cursor: zoom-in;
  }

  .full-image {
    max-width: 100%;
    max-height: calc(100vh - 280px);
    object-fit: contain;
    border-radius: 10px;
    box-shadow: 0px 4px 4px 0px rgba(0, 0, 0, 0.25);
  }

  /* ==========================================================================
     Progressive loading: show blurred preview while full-res fetches
     ========================================================================== */

  .image-wrapper.progressive {
    position: relative;
  }

  .preview-placeholder {
    filter: blur(2px);
    transition: filter 0.3s ease;
  }

  .progressive-overlay {
    position: absolute;
    top: 12px;
    right: 12px;
    background: rgba(0, 0, 0, 0.4);
    border-radius: 50%;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* ==========================================================================
     Loading state
     ========================================================================== */

  .image-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px;
  }

  .loading-spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--color-grey-20, #eaeaea);
    border-top-color: var(--color-primary-50, #5b8dd9);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  .loading-spinner.small {
    width: 18px;
    height: 18px;
    border-width: 2px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ==========================================================================
     Error state
     ========================================================================== */

  .error-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 32px;
    gap: 12px;
  }

  .error-icon {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--color-error-20, #f5c0c0);
    color: var(--color-error-70, #b04a4a);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    font-weight: 700;
  }

  .error-message {
    font-size: 14px;
    color: var(--color-grey-60, #666);
    margin: 0;
    max-width: 400px;
  }

  /* ==========================================================================
     Dark mode
     ========================================================================== */

  :global(.dark) .full-image {
    box-shadow: 0px 4px 4px 0px rgba(0, 0, 0, 0.5);
  }

  :global(.dark) .loading-spinner {
    border-color: var(--color-grey-70, #555);
    border-top-color: var(--color-primary-40, #7a9ed0);
  }

  :global(.dark) .error-message {
    color: var(--color-grey-40, #999);
  }
</style>
