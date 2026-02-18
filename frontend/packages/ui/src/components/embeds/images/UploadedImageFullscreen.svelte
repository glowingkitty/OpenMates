<!--
  frontend/packages/ui/src/components/embeds/images/UploadedImageFullscreen.svelte

  Fullscreen viewer for user-uploaded images (chat file uploads).

  Shows:
  - Full-resolution decrypted image from S3 (progressive: preview first, then full)
  - Download button for the original file
  - Close button (inherited from UnifiedEmbedFullscreen)

  Does NOT show prompt/model info — uploaded images are user photos, not AI-generated.

  Props mirror the files/aesKey/aesNonce structure returned by the uploads microservice,
  which matches the generate_task.py structure so the same imageEmbedCrypto utilities work.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';

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
    /** Original filename for the download */
    filename?: string;
    /** Close handler */
    onClose: () => void;
  }

  let {
    s3BaseUrl,
    files,
    aesKey,
    aesNonce,
    filename = 'image',
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

  /**
   * Load the full-resolution image from S3 with progressive enhancement.
   * 1. Show the cached preview immediately (typically already decrypted by
   *    the inline message card, so it appears with zero latency).
   * 2. Fetch + decrypt the full-resolution variant in the background.
   * 3. Swap to full-res when ready.
   */
  async function loadFullImage() {
    if (!s3BaseUrl || !aesKey || !aesNonce) return;
    if (fullImageUrl) return;

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
      console.error('[UploadedImageFullscreen] Failed to load full image:', err);
      imageError = err instanceof Error ? err.message : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }

  // Auto-load on mount
  $effect(() => {
    if (!fullImageUrl && !isLoadingImage) {
      loadFullImage();
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
  appId="uploads"
  skillId="upload"
  skillIconName="image"
  skillName=""
  showStatus={false}
  showSkillIcon={false}
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
     Main container: centers the image within the fullscreen panel.
     ========================================================================== */

  .uploaded-image-fullscreen {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    overflow: auto;
    padding: 24px;
    box-sizing: border-box;
  }

  /* ==========================================================================
     Image wrapper + link
     ========================================================================== */

  .image-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
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
