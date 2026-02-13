<!--
  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
  
  Fullscreen view for Image Generate embeds.
  Uses UnifiedEmbedFullscreen as base and provides image-specific content.
  
  Shows:
  - Full resolution decrypted image from S3
  - Prompt text
  - Model, aspect ratio, resolution metadata
  - Download button for original PNG
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text, settingsDeepLink, panelState } from '@repo/ui';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';
  import { generateImageFilename, embedPngMetadata } from './imageDownloadUtils';
  import { modelsMetadata } from '../../../data/modelsMetadata';
  import { getProviderIconUrl } from '../../../data/providerIcons';
  
  /**
   * Props for image generate embed fullscreen
   */
  interface Props {
    /** Image prompt */
    prompt?: string;
    /** Model reference */
    model?: string;
    /** Aspect ratio */
    aspectRatio?: string;
    /** S3 base URL for image files */
    s3BaseUrl?: string;
    /** Files metadata from embed content */
    files?: {
      preview?: { s3_key: string; width: number; height: number; format: string };
      full?: { s3_key: string; width: number; height: number; format: string };
      original?: { s3_key: string; width: number; height: number; format: string };
    };
    /** AES key for image decryption */
    aesKey?: string;
    /** AES nonce for image decryption */
    aesNonce?: string;
    /** Embed status */
    status?: string;
    /** Error message if any */
    error?: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
     /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
    /** Skill identifier ('generate' or 'generate_draft') - determines display title */
    skillId?: 'generate' | 'generate_draft';
    /** ISO timestamp of when the image was generated (for download metadata) */
    generatedAt?: string;
  }
  
  let {
    prompt,
    model,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    aspectRatio,
    s3BaseUrl,
    files,
    aesKey,
    aesNonce,
    status = 'finished',
    error,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat,
    skillId: skillIdProp = 'generate',
    generatedAt
  }: Props = $props();
  
  // Image state
  // Progressive loading: show the preview image instantly while the full-res version loads.
  // The preview is typically already cached from the inline embed, so it appears immediately.
  let previewImageUrl = $state<string | undefined>(undefined);
  let fullImageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  let isDownloading = $state(false);
  
  // Track retained S3 keys for cleanup
  let retainedPreviewKey: string | undefined = undefined;
  let retainedFullKey: string | undefined = undefined;
  
  // Skill display - use correct translation key based on skillId
  let skillName = $derived(
    skillIdProp === 'generate_draft'
      ? $text('embeds.image_generate_draft')
      : $text('embeds.image_generate')
  );
  const skillIconName = 'ai';
  
  // Look up full model metadata (name, logo) from modelsMetadata registry
  let modelMetadata = $derived(
    model ? modelsMetadata.find(m => m.id === model) : undefined
  );
  
  // Display name: prefer metadata name, fallback to extracting last segment of model ID
  let modelDisplayName = $derived.by(() => {
    if (modelMetadata?.name) return modelMetadata.name;
    if (!model) return '';
    const parts = model.split('/');
    return parts[parts.length - 1] || model;
  });
  
  // Provider icon URL resolved from metadata logo_svg field
  let providerIconUrl = $derived(
    modelMetadata?.logo_svg ? getProviderIconUrl(modelMetadata.logo_svg) : undefined
  );
  
  // Track copy feedback state
  let showCopied = $state(false);
  
  /**
   * Load the full-resolution image from S3 with progressive enhancement.
   * 1. Instantly show the cached preview (likely already decrypted by the inline preview)
   * 2. Fetch + decrypt the full-resolution image in the background
   * 3. Swap to full-res when ready
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
    
    // Step 2: Load the full-res version
    const fullFileData = files?.full || files?.preview;
    if (!fullFileData?.s3_key) return;
    
    // Check cache for full-res too
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
      console.debug('[ImageGenerateEmbedFullscreen] Loading full image from S3:', fullFileData.s3_key);
      const blob = await fetchAndDecryptImage(s3BaseUrl, fullFileData.s3_key, aesKey, aesNonce);
      fullImageUrl = URL.createObjectURL(blob);
      retainedFullKey = fullFileData.s3_key;
      retainCachedImage(fullFileData.s3_key);
    } catch (err) {
      console.error('[ImageGenerateEmbedFullscreen] Failed to load full image:', err);
      imageError = err instanceof Error ? err.message : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }
  
  // Auto-load full image on mount
  $effect(() => {
    if (status === 'finished' && !fullImageUrl && !isLoadingImage) {
      loadFullImage();
    }
  });
  
  // Cleanup: release cached image references on unmount
  onDestroy(() => {
    if (retainedPreviewKey) releaseCachedImage(retainedPreviewKey);
    if (retainedFullKey) releaseCachedImage(retainedFullKey);
  });
  
  /**
   * Download the original PNG image with a prompt-based filename and
   * embedded PNG tEXt metadata (prompt, model, software).
   * The backend already injects XMP metadata before encryption; the tEXt
   * chunks we add here provide an additional layer that is more widely
   * visible in file managers (macOS Finder, Windows Explorer, etc.).
   */
  async function handleDownload() {
    if (!files?.original?.s3_key || !s3BaseUrl || !aesKey || !aesNonce) return;
    if (isDownloading) return;
    
    isDownloading = true;
    
    try {
      const blob = await fetchAndDecryptImage(s3BaseUrl, files.original.s3_key, aesKey, aesNonce);
      const ext = files.original.format || 'png';
      
      // Embed PNG tEXt metadata (prompt, model, software) into the image bytes.
      // This makes the metadata visible in macOS Finder, Preview, and other viewers.
      let downloadBlob: Blob = blob;
      if (ext === 'png') {
        const arrayBuffer = await blob.arrayBuffer();
        const metadataBytes = embedPngMetadata(arrayBuffer, {
          prompt,
          model,
          software: 'OpenMates',
          generatedAt
        });
        // Copy into a plain ArrayBuffer to satisfy BlobPart typing
        const ab = new ArrayBuffer(metadataBytes.byteLength);
        new Uint8Array(ab).set(metadataBytes);
        downloadBlob = new Blob([ab], { type: 'image/png' });
      }
      
      // Generate a human-readable filename from the prompt
      const filename = generateImageFilename(prompt, ext);
      
      // Create download link
      const url = URL.createObjectURL(downloadBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('[ImageGenerateEmbedFullscreen] Failed to download original:', err);
    } finally {
      isDownloading = false;
    }
  }
  
  /**
   * Copy the prompt text to clipboard
   */
  async function handleCopyPrompt() {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      showCopied = true;
      setTimeout(() => { showCopied = false; }, 1500);
    } catch (err) {
      console.error('[ImageGenerateEmbedFullscreen] Failed to copy prompt:', err);
    }
  }
  
  /**
   * Navigate to the images app skill settings page in the app store.
   * Deep links to the skill page for the current skill (generate or generate_draft).
   */
  function handleModelClick() {
    const skillPath = skillIdProp === 'generate_draft' ? 'generate_draft' : 'generate';
    settingsDeepLink.set(`app_store/images/skill/${skillPath}`);
    panelState.openSettings();
  }
</script>

<UnifiedEmbedFullscreen
  appId="images"
  skillId={skillIdProp}
  {skillIconName}
  {skillName}
  showStatus={true}
  showSkillIcon={true}
  title=""
  {onClose}
  onDownload={files?.original ? handleDownload : undefined}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="image-fullscreen">
      {#if error}
        <!-- Error state -->
        <div class="error-container">
          <div class="error-icon">!</div>
          <h3 class="error-title">{$text('embeds.image_generate.error')}</h3>
          <p class="error-message">{error}</p>
        </div>
      {:else}
        <!-- Image display with progressive loading:
             1. Show cached preview instantly (blurred) while full-res loads
             2. Swap to full-res when ready
             On desktop this sits on the right; on narrow containers it appears first (top via CSS order). -->
        <div class="image-section">
          {#if fullImageUrl}
            <div class="image-wrapper">
              <img src={fullImageUrl} alt={prompt || 'Generated image'} class="full-image" />
            </div>
          {:else if previewImageUrl && isLoadingImage}
            <!-- Progressive: show preview while full-res loads -->
            <div class="image-wrapper progressive">
              <img src={previewImageUrl} alt={prompt || 'Generated image'} class="full-image preview-placeholder" />
              <div class="progressive-overlay">
                <div class="loading-spinner small"></div>
              </div>
            </div>
          {:else if isLoadingImage}
            <div class="image-loading">
              <div class="loading-spinner"></div>
              <span class="loading-text">{$text('embeds.image_generate.loading')}</span>
            </div>
          {:else if imageError}
            <div class="error-container">
              <div class="error-icon">!</div>
              <p class="error-message">{imageError}</p>
            </div>
          {/if}
        </div>

        <!-- Prompt area: "Generated by" line + quote card with prompt text.
             On desktop (wide containers) this sits on the left; on narrow containers it goes below the image. -->
        <div class="prompt-area">
          <!-- "Generated by {Model}" line with provider icon - clickable to open images skill settings -->
          {#if modelDisplayName}
            <button class="generated-by-line" onclick={handleModelClick}>
              {#if providerIconUrl}
                <img src={providerIconUrl} alt="" class="provider-icon" />
              {/if}
              <span class="generated-by-text">
                {$text('embeds.image_generate.generated_by')} {modelDisplayName}
              </span>
            </button>
          {/if}
          
          <!-- Prompt quote card with decorative quote icons -->
          {#if prompt}
            <div class="quote-card">
              <!-- Opening quote icon (bottom-left) -->
              <div class="quote-icon quote-open clickable-icon icon_quote"></div>
              
              <!-- Closing quote icon (top-right, rotated 180deg) -->
              <div class="quote-icon quote-close clickable-icon icon_quote"></div>
              
              <p class="prompt-text">{prompt}</p>
              
              <!-- Copy prompt button (bottom-right) -->
              <button
                class="copy-prompt-btn"
                onclick={handleCopyPrompt}
                title={showCopied ? 'Copied!' : 'Copy prompt'}
                aria-label="Copy prompt"
              >
                <span class="clickable-icon icon_copy copy-icon"></span>
              </button>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Main Layout Container
     Wide containers: side-by-side (image left, prompt right)
     Narrow containers: stacked (image top, prompt below)
     Uses @container queries (not @media) for responsive layout
     since the fullscreen panel width depends on context, not viewport.
     =========================================== */
  
  .image-fullscreen {
    display: flex;
    flex-direction: row;
    width: 100%;
    height: 100%;
    overflow: auto;
    align-items: center;
    gap: 0;
  }
  
  /* ===========================================
     Image Section (left on wide, top on narrow)
     =========================================== */
  
  .image-section {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 0;
    min-width: 0;
    padding: 24px;
  }
  
  .image-wrapper {
    max-width: 100%;
    max-height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .full-image {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 10px;
    box-shadow: 0px 4px 4px 0px rgba(0, 0, 0, 0.25);
  }
  
  /* Progressive loading: show blurred preview while full-res loads */
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
  
  .loading-spinner.small {
    width: 18px;
    height: 18px;
    border-width: 2px;
  }
  
  /* ===========================================
     Prompt Area (right on wide, below image on narrow)
     Contains "Generated by" line and quote card.
     Vertically centered alongside the image on wide layouts.
     =========================================== */
  
  .prompt-area {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 24px 24px 24px 0;
    align-self: center;
    max-width: 380px;
    flex-shrink: 0;
  }
  
  /* "Generated by {Model}" line with provider icon - clickable to open model settings.
     Simple text button, no background pill. Uses cursor:pointer and subtle hover. */
  .generated-by-line {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0;
    background: none;
    border: none;
    cursor: pointer;
    align-self: flex-start;
  }
  
  .generated-by-line:hover .generated-by-text {
    text-decoration: underline;
  }
  
  .provider-icon {
    width: 19px;
    height: 19px;
    flex-shrink: 0;
  }
  
  .generated-by-text {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.25;
    color: var(--color-grey-60, #666);
  }
  
  /* ===========================================
     Quote Card - prompt text with decorative quotes
     White rounded card (30px radius).
     Prompt text uses a darker grey for better readability.
     =========================================== */
  
  .quote-card {
    position: relative;
    background-color: var(--color-grey-0, #ffffff);
    border-radius: 30px;
    padding: 24px 50px;
    min-height: 80px;
  }
  
  /* Quote icons - uses CSS mask with quote.svg from icons system */
  .quote-icon {
    position: absolute;
    width: 20px;
    height: 20px;
    background: var(--color-grey-100, #000) !important;
    cursor: default;
  }
  
  .quote-open {
    left: 12px;
    bottom: 12px;
  }
  
  .quote-close {
    right: 12px;
    top: 12px;
    transform: rotate(180deg);
  }
  
  /* Prompt text - darker color (#3A3A3A) for better visibility */
  .prompt-text {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 16px;
    font-weight: 500;
    line-height: 1.25;
    color: var(--color-grey-80, #3A3A3A);
    margin: 0;
    word-break: break-word;
    white-space: pre-wrap;
  }
  
  /* Copy prompt button - bottom-right corner of quote card */
  .copy-prompt-btn {
    position: absolute;
    right: 12px;
    bottom: 12px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.5;
    transition: opacity 0.2s ease;
  }
  
  .copy-prompt-btn:hover {
    opacity: 1;
  }
  
  .copy-icon {
    width: 19px;
    height: 19px;
    background: var(--color-primary-50, #5b8dd9) !important;
  }
  
  /* ===========================================
     Loading State
     =========================================== */
  
  .image-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
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
  
  .loading-text {
    font-size: 14px;
    color: var(--color-grey-50, #888);
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  /* ===========================================
     Error State
     =========================================== */
  
  .error-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    text-align: center;
    padding: 32px;
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
    margin-bottom: 16px;
  }
  
  .error-title {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 8px 0;
    color: var(--color-grey-90, #1a1a1a);
  }
  
  .error-message {
    font-size: 14px;
    color: var(--color-grey-60, #666);
    margin: 0;
    max-width: 400px;
  }
  
  /* ===========================================
     Dark Mode
     =========================================== */
  
  :global(.dark) .quote-card {
    background-color: var(--color-grey-90, #1a1a1a);
  }
  
  :global(.dark) .quote-icon {
    background: var(--color-grey-0, #fff) !important;
  }
  
  :global(.dark) .prompt-text {
    color: var(--color-grey-20, #ddd);
  }
  
  :global(.dark) .generated-by-text {
    color: var(--color-grey-40, #999);
  }
  
  :global(.dark) .copy-icon {
    background: var(--color-primary-40, #7a9ed0) !important;
  }
  
  :global(.dark) .full-image {
    box-shadow: 0px 4px 4px 0px rgba(0, 0, 0, 0.5);
  }
  
  :global(.dark) .loading-spinner {
    border-color: var(--color-grey-70, #555);
    border-top-color: var(--color-primary-40, #7a9ed0);
  }
  
  :global(.dark) .loading-text {
    color: var(--color-grey-50, #888);
  }
  
  :global(.dark) .error-title {
    color: var(--color-grey-10, #f5f5f5);
  }
  
  :global(.dark) .error-message {
    color: var(--color-grey-40, #999);
  }
  
  /* ===========================================
     Responsive: Narrow container layout (stacked, image on top)
     Uses @container queries referencing the "fullscreen" container
     defined in UnifiedEmbedFullscreen, so layout adapts to the
     panel width, not the viewport width.
     =========================================== */
  
  @container fullscreen (max-width: 600px) {
    .image-fullscreen {
      flex-direction: column;
      align-items: stretch;
      overflow-y: auto;
      overflow-x: hidden;
    }
    
    /* On narrow: image appears first (top), prompt area below */
    .image-section {
      order: 1;
      flex: none;
      padding: 16px;
      width: 100%;
    }
    
    /* Ensure the image fits the container width without horizontal scroll */
    .full-image {
      max-width: 100%;
      width: 100%;
      height: auto;
      max-height: none;
    }
    
    .prompt-area {
      order: 2;
      align-self: stretch;
      max-width: none;
      padding: 0 16px 16px 16px;
    }
    
    .quote-card {
      padding: 20px 46px;
    }
  }
</style>
