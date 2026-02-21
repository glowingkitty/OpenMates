<!--
  frontend/packages/ui/src/components/embeds/images/UploadedImageFullscreen.svelte

  Fullscreen viewer for user-uploaded image embeds in the message editor.

  Shows:
  - Full-resolution decrypted image from S3 (progressive: preview first, then full)
    OR a local blob URL as fallback when the user is not authenticated (no S3 upload).
  - Download button for the original file (S3 path only)
  - Close button (inherited from UnifiedEmbedFullscreen)
  - BasicInfosBar with truncated filename + "Signup to upload…" or file type/size subtitle

  Does NOT show prompt/model info — uploaded images are user photos, not AI-generated.

  Props mirror the files/aesKey/aesNonce structure returned by the uploads microservice,
  which matches the generate_task.py structure so the same imageEmbedCrypto utilities work.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';
  import { text } from '@repo/ui';

  /** Max display length for the filename in the bottom bar title (chars) */
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
    /** File size in bytes (from the original File object) — shown in info bar subtitle */
    fileSize?: number;
    /** File MIME type (e.g. 'image/jpeg') — shown in info bar subtitle */
    fileType?: string;
    /** Close handler */
    onClose: () => void;
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
  }: Props = $props();

  // -------------------------------------------------------------------------
  // Image loading state
  // Progressive loading: show cached preview instantly while full-res loads.
  // -------------------------------------------------------------------------

  let previewImageUrl = $state<string | undefined>(undefined);
  let fullImageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  let isDownloading = $state(false);

  // Track retained S3 keys so we release LRU cache references on unmount
  let retainedPreviewKey: string | undefined = undefined;
  let retainedFullKey: string | undefined = undefined;

  // -------------------------------------------------------------------------
  // Info bar: truncated filename + subtitle
  // -------------------------------------------------------------------------

  /**
   * Truncate filename to MAX_FILENAME_LENGTH characters, keeping the extension
   * visible if present (mirrors the logic in ImageEmbedPreview.svelte).
   */
  let infoBarTitle = $derived.by(() => {
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
   * Info bar subtitle:
   * - Unauthenticated: "Signup to upload…"
   * - Authenticated: "JPEG · 1.2 MB" (or just type or just size)
   */
  let infoBarSubtitle = $derived.by(() => {
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

    isLoadingImage = true;
    imageError = undefined;

    try {
      console.debug('[UploadedImageFullscreen] Loading full image from S3:', fullFileData.s3_key);
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
      console.error('[UploadedImageFullscreen] Failed to load full image:', errMsg, err);
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

    if (!fullImageUrl && !isLoadingImage) {
      // Use the locally-read values so the compiler knows they're dependencies.
      if (!currentS3 || !currentKey || !currentNonce) {
        // Blob path: use local src when S3 is not available
        if (currentSrc) {
          fullImageUrl = currentSrc;
          console.debug('[UploadedImageFullscreen] Using local blob URL (no S3 data available)');
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
      console.error('[UploadedImageFullscreen] Failed to download original:', err);
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
  skillName={infoBarTitle}
  customStatusText={infoBarSubtitle}
  showStatus={true}
  showSkillIcon={false}
  showShare={!!files?.original}
  title=""
  {onClose}
  onDownload={files?.original ? handleDownload : undefined}
>
  {#snippet content()}
    <div class="uploaded-image-fullscreen">
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
        </div>
      {:else if previewImageUrl && isLoadingImage}
        <!-- Progressive: show blurred preview while full-res loads -->
        <div class="image-wrapper progressive">
          <img src={previewImageUrl} alt={filename} class="full-image preview-placeholder" />
          <div class="progressive-overlay">
            <div class="loading-spinner small"></div>
          </div>
        </div>
      {:else if isLoadingImage}
        <div class="image-loading">
          <div class="loading-spinner"></div>
        </div>
      {:else}
        <!-- Nothing yet — loading starts via $effect above -->
        <div class="image-loading">
          <div class="loading-spinner"></div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ==========================================================================
     Override the parent UnifiedEmbedFullscreen content-area so the image
     fills the full panel without the normal 120px bottom padding.
     We position the image container absolutely so it reaches edge-to-edge,
     behind the absolutely-positioned bottom bar and top bar.
     ========================================================================== */

  :global(.unified-embed-fullscreen-overlay:has(.uploaded-image-fullscreen) .content-area) {
    padding-bottom: 0;
    overflow: hidden;
  }

  /* ==========================================================================
     Main container: fills the entire fullscreen area (absolute, edge-to-edge).
     The top/bottom bars from UnifiedEmbedFullscreen are positioned above us
     via their own z-index so they remain clickable.
     ========================================================================== */

  .uploaded-image-fullscreen {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    /* Leave room for the bottom bar (approx 100px) and top bar (approx 70px) */
    padding: 80px 24px 110px;
    box-sizing: border-box;
    overflow: hidden;
  }

  /* ==========================================================================
     Image wrapper + link
     ========================================================================== */

  .image-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    max-width: 100%;
    max-height: 100%;
  }

  .image-link {
    display: flex;
    align-items: center;
    justify-content: center;
    max-width: 100%;
    max-height: 100%;
    cursor: zoom-in;
  }

  .full-image {
    max-width: 100%;
    max-height: 100%;
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
    height: 100%;
    min-height: 200px;
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
