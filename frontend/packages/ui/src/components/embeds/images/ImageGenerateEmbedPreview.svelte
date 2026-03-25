<!--
  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
  
  Preview component for Image Generate embeds (images/generate and images/generate_draft).
  Uses UnifiedEmbedPreview as base and provides image-specific details content.
  
  Shows:
  - Processing state: input prompt text (no skeleton/loading image)
  - Finished (loading): input prompt text while image decrypts
  - Finished (loaded): decrypted preview image from S3
  - Error state: error message
  
  The image is fetched from S3 as an encrypted blob and decrypted client-side
  using AES-256-GCM via the Web Crypto API.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from './imageEmbedCrypto';
  import { getModelDisplayName, getModelByNameOrId } from '../../../utils/modelDisplayName';
  import { getProviderIconUrl } from '../../../data/providerIcons';
  import { resolveEmbed, decodeToonContent } from '../../../services/embedResolver';
  
  /**
   * Image embed content structure from the backend
   */
  interface ImageEmbedData {
    app_id?: string;
    skill_id?: string;
    type?: string;
    status?: string;
    prompt?: string;
    model?: string;
    aspect_ratio?: string;
    generated_at?: string;
    s3_base_url?: string;
    files?: {
      preview?: { s3_key: string; width: number; height: number; format: string };
      full?: { s3_key: string; width: number; height: number; format: string };
      original?: { s3_key: string; width: number; height: number; format: string };
    };
    aes_key?: string;
    aes_nonce?: string;
    error?: string;
    /** Embed IDs of the source images used for image-to-image generation */
    input_embed_ids?: string[];
  }
  
  /**
   * Props for image generate embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Skill identifier ('generate' or 'generate_draft') - determines display title */
    skillId?: 'generate' | 'generate_draft';
    /** Image prompt */
    prompt?: string;
    /** Model ID used for generation (e.g., "flux-schnell", "gemini-3-pro-image-preview") */
    model?: string;
    /** S3 base URL for image files */
    s3BaseUrl?: string;
    /** Files metadata from embed content */
    files?: ImageEmbedData['files'];
    /** AES key for image decryption */
    aesKey?: string;
    /** AES nonce for image decryption */
    aesNonce?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Error message if any */
    error?: string;
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
    /** Embed IDs of the source images used for image-to-image generation */
    inputEmbedIds?: string[];
  }
  
  let {
    id,
    skillId: skillIdProp = 'generate',
    prompt: promptProp,
    model: modelProp,
    s3BaseUrl: s3BaseUrlProp,
    files: filesProp,
    aesKey: aesKeyProp,
    aesNonce: aesNonceProp,
    status: statusProp,
    error: errorProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen,
    inputEmbedIds: inputEmbedIdsProp
  }: Props = $props();
  
  // Local reactive state — updated via handleEmbedDataUpdated callback
  let localPrompt = $state<string | undefined>(undefined);
  let localModel = $state<string | undefined>(undefined);
  let localS3BaseUrl = $state<string | undefined>(undefined);
  let localFiles = $state<ImageEmbedData['files'] | undefined>(undefined);
  let localAesKey = $state<string | undefined>(undefined);
  let localAesNonce = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let storeResolved = $state(false);
  let localError = $state<string | undefined>(undefined);
  let localTaskId = $state<string | undefined>(undefined);
  let localInputEmbedIds = $state<string[] | undefined>(undefined);

  // Decrypted thumbnail URLs for input (reference) images — keyed by embed ID
  let inputImageUrls = $state<Map<string, string>>(new Map());
  // S3 keys retained from the cache so we can release on unmount
  let retainedInputKeys: string[] = [];
  
  // Image blob URL for rendering
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  
  // Track which S3 key we retained so we can release on unmount
  let retainedS3Key: string | undefined = undefined;
  
  // Lazy loading: only fetch when the embed scrolls into view
  let isInView = $state(false);
  let containerRef: HTMLElement | undefined = $state(undefined);
  let observer: IntersectionObserver | undefined = undefined;
  
  // Set up IntersectionObserver for lazy loading
  $effect(() => {
    if (!containerRef) return;
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          isInView = true;
          // Once visible, no need to keep observing
          observer?.disconnect();
        }
      },
      { rootMargin: '200px' } // Start loading 200px before entering viewport
    );
    observer.observe(containerRef);
    return () => observer?.disconnect();
  });
  
  // Cleanup: release cached blob URL references on unmount
  onDestroy(() => {
    if (retainedS3Key) {
      releaseCachedImage(retainedS3Key);
      retainedS3Key = undefined;
    }
    for (const key of retainedInputKeys) {
      releaseCachedImage(key);
    }
    retainedInputKeys = [];
    observer?.disconnect();
  });
  
  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      localPrompt = promptProp;
      localModel = modelProp;
      localS3BaseUrl = s3BaseUrlProp;
      localFiles = filesProp;
      localAesKey = aesKeyProp;
      localAesNonce = aesNonceProp;
      localStatus = statusProp || 'processing';
      localError = errorProp;
      localTaskId = taskIdProp;
      localInputEmbedIds = inputEmbedIdsProp;
    }
  });
  
  // Derived state
  let prompt = $derived(localPrompt);
  let model = $derived(localModel);
  let status = $derived(localStatus);
  let error = $derived(localError);
  let taskId = $derived(localTaskId);
  let files = $derived(localFiles);
  let s3BaseUrl = $derived(localS3BaseUrl);
  let aesKey = $derived(localAesKey);
  let aesNonce = $derived(localAesNonce);
  let inputEmbedIds = $derived(localInputEmbedIds);
  
  // Human-readable model name resolved from model ID via frontend metadata
  let modelDisplayName = $derived(model ? getModelDisplayName(model) : undefined);
  
  // Model metadata for icon display
  let modelMetadata = $derived(model ? getModelByNameOrId(model) : undefined);
  let modelIconUrl = $derived(modelMetadata?.logo_svg ? getProviderIconUrl(modelMetadata.logo_svg) : undefined);
  
  // Skill display name - use correct translation key based on skillId
  // 'generate' -> "Generate", 'generate_draft' -> "Generate Draft"
  const skillIconName = 'ai';
  let skillName = $derived(
    skillIdProp === 'generate_draft'
      ? $text('embeds.image_generate_draft')
      : $text('common.generate')
  );
  
  
  /**
   * Load and decrypt preview thumbnails for input (reference) images.
   * Resolves each embed ID, decodes TOON content, then fetches+decrypts the
   * preview variant using the same crypto pipeline as the output image.
   */
  async function loadInputImages(embedIds: string[]) {
    for (const embedId of embedIds) {
      if (inputImageUrls.has(embedId)) continue; // already loaded

      try {
        const embedData = await resolveEmbed(embedId);
        if (!embedData?.content) continue;

        const content = await decodeToonContent(embedData.content);
        if (!content) continue;

        const inputS3BaseUrl = content.s3_base_url as string | undefined;
        const inputFiles = content.files as Record<string, { s3_key: string }> | undefined;
        const inputAesKey = content.aes_key as string | undefined;
        const inputAesNonce = content.aes_nonce as string | undefined;

        const previewKey = inputFiles?.preview?.s3_key;
        if (!previewKey || !inputS3BaseUrl || !inputAesKey || !inputAesNonce) continue;

        // Check shared cache first
        const cached = getCachedImageUrl(previewKey);
        if (cached) {
          retainCachedImage(previewKey);
          retainedInputKeys.push(previewKey);
          inputImageUrls = new Map(inputImageUrls).set(embedId, cached);
          continue;
        }

        const blob = await fetchAndDecryptImage(inputS3BaseUrl, previewKey, inputAesKey, inputAesNonce);
        const url = URL.createObjectURL(blob);
        retainCachedImage(previewKey);
        retainedInputKeys.push(previewKey);
        inputImageUrls = new Map(inputImageUrls).set(embedId, url);
      } catch (err) {
        console.warn('[ImageGenerateEmbedPreview] Failed to load input image thumbnail:', embedId, err);
      }
    }
  }

  // Load input image thumbnails when embed IDs are available and embed is in view
  $effect(() => {
    if (isInView && inputEmbedIds && inputEmbedIds.length > 0) {
      loadInputImages(inputEmbedIds);
    }
  });

  /**
   * Load and decrypt the preview image from S3.
   * Uses the shared in-memory cache to avoid redundant fetch+decrypt cycles.
   */
  async function loadPreviewImage() {
    const s3Key = files?.preview?.s3_key;
    if (!s3Key || !s3BaseUrl || !aesKey || !aesNonce) {
      console.debug('[ImageGenerateEmbedPreview] Missing data for image load:', {
        hasFiles: !!s3Key,
        hasS3BaseUrl: !!s3BaseUrl,
        hasAesKey: !!aesKey,
        hasAesNonce: !!aesNonce,
      });
      return;
    }
    
    // Don't reload if we already have an image
    if (imageUrl) return;
    
    // Check shared cache first (instant hit if another component already decrypted this)
    const cachedUrl = getCachedImageUrl(s3Key);
    if (cachedUrl) {
      imageUrl = cachedUrl;
      // Release previous key if switching images
      if (retainedS3Key && retainedS3Key !== s3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = s3Key;
      retainCachedImage(s3Key);
      return;
    }
    
    isLoadingImage = true;
    imageError = undefined;
    
    try {
      console.debug('[ImageGenerateEmbedPreview] Loading preview image from S3:', s3Key);
      const blob = await fetchAndDecryptImage(s3BaseUrl, s3Key, aesKey, aesNonce);
      imageUrl = URL.createObjectURL(blob);
      // Retain reference in shared cache so blob URL isn't revoked while we're using it
      if (retainedS3Key && retainedS3Key !== s3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = s3Key;
      retainCachedImage(s3Key);
      console.debug('[ImageGenerateEmbedPreview] Preview image loaded successfully');
    } catch (err) {
      // DOMException from Web Crypto API has no enumerable properties and serializes as {}.
      // Extract name and message explicitly for meaningful logging.
      const errorDetail = err instanceof Error
        ? `${err.name}: ${err.message || '(no message)'}` 
        : String(err);
      console.error('[ImageGenerateEmbedPreview] Failed to load preview image:', errorDetail);
      // DOMException.message is often empty for OperationError, so fall back to name or generic text
      imageError = err instanceof Error 
        ? (err.message || err.name || 'Failed to decrypt image') 
        : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }
  
  // Auto-load image when status becomes finished, data is available, AND the embed is in view.
  // The IntersectionObserver sets isInView=true when the embed is within 200px of the viewport,
  // preventing all images in a long chat from loading simultaneously.
  $effect(() => {
    if (isInView && status === 'finished' && files?.preview?.s3_key && s3BaseUrl && aesKey && aesNonce && !imageUrl && !isLoadingImage) {
      loadPreviewImage();
    }
  });
  
  /**
   * Handle embed data updates from server (processing -> finished transition)
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    console.debug('[ImageGenerateEmbedPreview] Received embed data update:', {
      embedId: id,
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }

    // Update content from decoded data
    if (data.decodedContent) {
      const content = data.decodedContent as unknown as ImageEmbedData;
      
      if (content.prompt) localPrompt = content.prompt;
      if (content.model) localModel = content.model;
      if (content.s3_base_url) localS3BaseUrl = content.s3_base_url;
      if (content.files) localFiles = content.files;
      if (content.aes_key) localAesKey = content.aes_key;
      if (content.aes_nonce) localAesNonce = content.aes_nonce;
      if (content.error) localError = content.error;
      if (Array.isArray(content.input_embed_ids)) localInputEmbedIds = content.input_embed_ids;
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="images"
  skillId={skillIdProp}
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showStatus={true}
  showSkillIcon={true}
  hasFullWidthImage={status === 'finished' && !!imageUrl && !error}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="image-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>
      {#if inputEmbedIds && inputEmbedIds.length > 0}
        <!-- Input image strip: 30px tall thumbnails shown above the main content -->
        <div class="input-images-strip">
          {#each inputEmbedIds as embedId (embedId)}
            {@const thumbUrl = inputImageUrls.get(embedId)}
            <div class="input-thumb">
              {#if thumbUrl}
                <img src={thumbUrl} alt="" class="input-thumb-img" />
              {:else}
                <div class="input-thumb-placeholder"></div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
      {#if status === 'finished' && !error && imageUrl}
        <!-- Finished state with loaded image: show decrypted image with model info overlay -->
        <div class="image-content">
          <div class="image-container">
            <img src={imageUrl} alt={prompt || 'Generated image'} class="preview-image" />
          </div>
          {#if modelDisplayName}
            <div class="image-model-badge">
              {#if modelIconUrl}
                <img src={modelIconUrl} alt="" class="model-icon" />
              {/if}
              <span class="generating-via">{$text('embeds.image_generate.generated_by')} {modelDisplayName}</span>
            </div>
          {/if}
        </div>
      {:else if status === 'finished' && !error && imageError}
        <!-- Finished state but image decryption failed -->
        <div class="image-error-small">
          <span class="error-icon-small">!</span>
          <span>{imageError}</span>
        </div>
      {:else if status !== 'error'}
        <!-- Processing state OR finished-but-still-loading-image: show the prompt text -->
        <div class="prompt-content">
          {#if prompt}
            {#if modelDisplayName}
              <div class="model-info-line">
                {#if modelIconUrl}
                  <img src={modelIconUrl} alt="" class="model-icon" />
                {/if}
                <span class="generating-via">{$text('embeds.image_generate.generating_via')} {modelDisplayName}:</span>
              </div>
            {/if}
            <span class="prompt-text">{prompt}</span>
          {:else}
            <div class="skeleton-lines">
              <div class="skeleton-line long"></div>
              <div class="skeleton-line short"></div>
            </div>
          {/if}
        </div>
      {:else}
        <!-- Error state -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{error || $text('embeds.image_generate.error')}</span>
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

  /* Input image thumbnails — 30px strip at the top */
  .input-images-strip {
    display: flex;
    flex-direction: row;
    gap: 4px;
    padding: 4px 8px;
    overflow-x: auto;
    overflow-y: hidden;
    flex-shrink: 0;
    background: var(--color-grey-5, #f8f8f8);
    scrollbar-width: none;
  }

  .input-images-strip::-webkit-scrollbar {
    display: none;
  }

  .input-thumb {
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    border-radius: 3px;
    overflow: hidden;
    border: 1px solid var(--color-grey-20, #e0e0e0);
  }

  .input-thumb-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .input-thumb-placeholder {
    width: 100%;
    height: 100%;
    background: var(--color-grey-15, #f0f0f0);
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  .image-preview.mobile {
    padding: 0;
  }
  
  /* Prompt content (processing state / image-loading state) */
  .prompt-content {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    padding: 16px 20px;
    box-sizing: border-box;
    overflow: hidden;
  }
  
  /* "Generating via {Model}:" label shown above the prompt during processing */
  .prompt-content .generating-via {
    font-size: 12px;
    font-weight: 600;
    color: var(--color-grey-50, #888);
    line-height: 1.4;
  }
  
  .model-info-line {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
  }
  
  .model-icon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
  }
  
  .prompt-content .prompt-text {
    font-size: 14px;
    color: var(--color-grey-70, #555);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }
  
  /* Skeleton lines fallback when prompt is not yet available */
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
  
  /* Image content (finished state) */
  .image-content {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  
  .image-container {
    width: 100%;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-10, #f5f5f5);
  }
  
  .preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  
  /* Model badge shown over finished images */
  .image-model-badge {
    position: absolute;
    bottom: 8px;
    left: 8px;
    background: rgba(0, 0, 0, 0.6);
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .image-model-badge .model-icon {
    width: 14px;
    height: 14px;
  }
  
  .image-content {
    position: relative;
  }
  
  /* Note: .image-prompt section was removed from the template to allow the image
     to extend into the BasicInfosBar area (via hasFullWidthImage negative margin). */
  
  /* Image load error */
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
  
  /* Error state */
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
  
  /* Mobile adjustments - no special handling needed since prompt was removed from preview */
  
  /* Dark mode support */
  :global(.dark) .prompt-content .generating-via {
    color: var(--color-grey-50, #888);
  }
  
  :global(.dark) .prompt-content .prompt-text {
    color: var(--color-grey-40, #aaa);
  }
  
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .image-container {
    background: var(--color-grey-90, #1a1a1a);
  }

  :global(.dark) .input-images-strip {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .input-thumb {
    border-color: var(--color-grey-70, #444);
  }

  :global(.dark) .input-thumb-placeholder {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .error-state {
    background: var(--color-error-95, #2a1515);
  }
  
  :global(.dark) .error-text {
    color: var(--color-error-40, #d07a7a);
  }
</style>
