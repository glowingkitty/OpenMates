<!--
  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
  
  Preview component for Image Generate embeds (images/generate and images/generate_draft).
  Uses UnifiedEmbedPreview as base and provides image-specific details content.
  
  Shows:
  - Processing state: shimmer skeleton + prompt text
  - Finished state: decrypted preview image from S3 + prompt + model label
  - Error state: error message
  
  The image is fetched from S3 as an encrypted blob and decrypted client-side
  using AES-256-GCM via the Web Crypto API.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage } from './imageEmbedCrypto';
  
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
  }
  
  /**
   * Props for image generate embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Image prompt */
    prompt?: string;
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
    onFullscreen?: () => void;
  }
  
  let {
    id,
    prompt: promptProp,
    s3BaseUrl: s3BaseUrlProp,
    files: filesProp,
    aesKey: aesKeyProp,
    aesNonce: aesNonceProp,
    status: statusProp,
    error: errorProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state — updated via handleEmbedDataUpdated callback
  let localPrompt = $state<string | undefined>(undefined);
  let localS3BaseUrl = $state<string | undefined>(undefined);
  let localFiles = $state<ImageEmbedData['files'] | undefined>(undefined);
  let localAesKey = $state<string | undefined>(undefined);
  let localAesNonce = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localError = $state<string | undefined>(undefined);
  let localTaskId = $state<string | undefined>(undefined);
  
  // Image blob URL for rendering
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localPrompt = promptProp;
    localS3BaseUrl = s3BaseUrlProp;
    localFiles = filesProp;
    localAesKey = aesKeyProp;
    localAesNonce = aesNonceProp;
    localStatus = statusProp || 'processing';
    localError = errorProp;
    localTaskId = taskIdProp;
  });
  
  // Derived state
  let prompt = $derived(localPrompt);
  let status = $derived(localStatus);
  let error = $derived(localError);
  let taskId = $derived(localTaskId);
  let files = $derived(localFiles);
  let s3BaseUrl = $derived(localS3BaseUrl);
  let aesKey = $derived(localAesKey);
  let aesNonce = $derived(localAesNonce);
  
  // Skill display name
  const skillIconName = 'image';
  let skillName = $derived($text('embeds.image_generate.text'));
  
  // Truncate prompt for preview (2 lines max)
  let promptPreview = $derived.by(() => {
    if (!prompt) return '';
    const text = prompt.length > 100 ? prompt.substring(0, 100) + '...' : prompt;
    return text;
  });
  
  /**
   * Load and decrypt the preview image from S3
   */
  async function loadPreviewImage() {
    if (!files?.preview?.s3_key || !s3BaseUrl || !aesKey || !aesNonce) {
      console.debug('[ImageGenerateEmbedPreview] Missing data for image load:', {
        hasFiles: !!files?.preview?.s3_key,
        hasS3BaseUrl: !!s3BaseUrl,
        hasAesKey: !!aesKey,
        hasAesNonce: !!aesNonce,
      });
      return;
    }
    
    // Don't reload if we already have an image
    if (imageUrl) return;
    
    isLoadingImage = true;
    imageError = undefined;
    
    try {
      console.debug('[ImageGenerateEmbedPreview] Loading preview image from S3:', files.preview.s3_key);
      const blob = await fetchAndDecryptImage(s3BaseUrl, files.preview.s3_key, aesKey, aesNonce);
      imageUrl = URL.createObjectURL(blob);
      console.debug('[ImageGenerateEmbedPreview] Preview image loaded successfully');
    } catch (err) {
      console.error('[ImageGenerateEmbedPreview] Failed to load preview image:', err);
      imageError = err instanceof Error ? err.message : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }
  
  // Auto-load image when status becomes finished and we have the required data
  $effect(() => {
    if (status === 'finished' && files?.preview?.s3_key && s3BaseUrl && aesKey && aesNonce && !imageUrl && !isLoadingImage) {
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
    
    // Update content from decoded data
    if (data.decodedContent) {
      const content = data.decodedContent as unknown as ImageEmbedData;
      
      if (content.prompt) localPrompt = content.prompt;
      if (content.s3_base_url) localS3BaseUrl = content.s3_base_url;
      if (content.files) localFiles = content.files;
      if (content.aes_key) localAesKey = content.aes_key;
      if (content.aes_nonce) localAesNonce = content.aes_nonce;
      if (content.error) localError = content.error;
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="images"
  skillId="generate"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showStatus={true}
  showSkillIcon={true}
  hasFullWidthImage={status === 'finished' && !!imageUrl}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="image-preview" class:mobile={isMobileSnippet}>
      {#if status === 'processing'}
        <!-- Processing state: shimmer skeleton -->
        <div class="skeleton-content">
          <div class="skeleton-image"></div>
          {#if prompt}
            <div class="skeleton-prompt">
              <span class="prompt-text">{promptPreview}</span>
            </div>
          {:else}
            <div class="skeleton-lines">
              <div class="skeleton-line long"></div>
              <div class="skeleton-line short"></div>
            </div>
          {/if}
        </div>
      {:else if status === 'finished' && !error}
        <!-- Finished state: show decrypted image + prompt -->
        <div class="image-content">
          {#if imageUrl}
            <div class="image-container">
              <img src={imageUrl} alt={prompt || 'Generated image'} class="preview-image" />
            </div>
          {:else if isLoadingImage}
            <div class="image-container">
              <div class="skeleton-image loading"></div>
            </div>
          {:else if imageError}
            <div class="image-error-small">
              <span class="error-icon-small">!</span>
              <span>{imageError}</span>
            </div>
          {/if}
          
          {#if promptPreview}
            <div class="image-prompt">
              <span class="prompt-text">{promptPreview}</span>
            </div>
          {/if}
        </div>
      {:else}
        <!-- Error state -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{error || $text('embeds.image_generate.error.text')}</span>
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
  
  /* Skeleton loading state */
  .skeleton-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
    padding: 12px;
    box-sizing: border-box;
  }
  
  .skeleton-image {
    width: 100%;
    height: 120px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 6px;
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  .skeleton-image.loading {
    background: linear-gradient(90deg, var(--color-grey-15, #f0f0f0) 25%, var(--color-grey-10, #f5f5f5) 50%, var(--color-grey-15, #f0f0f0) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s ease-in-out infinite;
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
  
  .skeleton-prompt {
    padding: 6px 8px;
    background: var(--color-grey-10, #f5f5f5);
    border-radius: 4px;
  }
  
  .skeleton-prompt .prompt-text {
    font-size: 12px;
    color: var(--color-grey-50, #888);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
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
  
  .image-prompt {
    padding: 8px 12px;
    background: var(--color-grey-5, #fafafa);
    border-top: 1px solid var(--color-grey-15, #f0f0f0);
  }
  
  .image-prompt .prompt-text {
    font-size: 12px;
    color: var(--color-grey-60, #666);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  
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
  
  /* Mobile adjustments */
  .mobile .image-prompt .prompt-text {
    font-size: 11px;
  }
  
  /* Dark mode support */
  :global(.dark) .skeleton-image {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .skeleton-prompt {
    background: var(--color-grey-90, #1a1a1a);
  }
  
  :global(.dark) .skeleton-prompt .prompt-text {
    color: var(--color-grey-50, #888);
  }
  
  :global(.dark) .image-container {
    background: var(--color-grey-90, #1a1a1a);
  }
  
  :global(.dark) .image-prompt {
    background: var(--color-grey-95, #111);
    border-top-color: var(--color-grey-85, #252525);
  }
  
  :global(.dark) .image-prompt .prompt-text {
    color: var(--color-grey-40, #aaa);
  }
  
  :global(.dark) .error-state {
    background: var(--color-error-95, #2a1515);
  }
  
  :global(.dark) .error-text {
    color: var(--color-error-40, #d07a7a);
  }
</style>
