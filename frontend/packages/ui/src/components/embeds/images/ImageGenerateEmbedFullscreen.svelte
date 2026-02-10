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
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage } from './imageEmbedCrypto';
  
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
  }
  
  let {
    prompt,
    model,
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
    onShowChat
  }: Props = $props();
  
  // Image state
  let fullImageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  let isDownloading = $state(false);
  
  // Skill display
  let skillName = $derived($text('embeds.image_generate.text'));
  const skillIconName = 'image';
  
  // Format model name for display
  let modelDisplay = $derived.by(() => {
    if (!model) return '';
    const parts = model.split('/');
    return parts[parts.length - 1] || model;
  });
  
  // Resolution display
  let resolutionDisplay = $derived.by(() => {
    const f = files?.full || files?.original;
    if (!f) return '';
    return `${f.width} x ${f.height}`;
  });
  
  /**
   * Load and decrypt the full-resolution image from S3
   */
  async function loadFullImage() {
    // Use 'full' format for fullscreen, fallback to 'preview'
    const fileData = files?.full || files?.preview;
    if (!fileData?.s3_key || !s3BaseUrl || !aesKey || !aesNonce) return;
    
    if (fullImageUrl) return;
    
    isLoadingImage = true;
    imageError = undefined;
    
    try {
      console.debug('[ImageGenerateEmbedFullscreen] Loading full image from S3:', fileData.s3_key);
      const blob = await fetchAndDecryptImage(s3BaseUrl, fileData.s3_key, aesKey, aesNonce);
      fullImageUrl = URL.createObjectURL(blob);
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
  
  /**
   * Download the original PNG image
   */
  async function handleDownload() {
    if (!files?.original?.s3_key || !s3BaseUrl || !aesKey || !aesNonce) return;
    if (isDownloading) return;
    
    isDownloading = true;
    
    try {
      const blob = await fetchAndDecryptImage(s3BaseUrl, files.original.s3_key, aesKey, aesNonce);
      
      // Create download link
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `generated-image-${Date.now()}.png`;
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
</script>

<UnifiedEmbedFullscreen
  appId="images"
  skillId="generate"
  {skillIconName}
  {skillName}
  showStatus={false}
  showSkillIcon={false}
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
          <h3 class="error-title">{$text('embeds.image_generate.error.text')}</h3>
          <p class="error-message">{error}</p>
        </div>
      {:else}
        <!-- Image display -->
        <div class="image-section">
          {#if isLoadingImage}
            <div class="image-loading">
              <div class="loading-spinner"></div>
              <span class="loading-text">{$text('embeds.image_generate.loading.text')}</span>
            </div>
          {:else if fullImageUrl}
            <div class="image-wrapper">
              <img src={fullImageUrl} alt={prompt || 'Generated image'} class="full-image" />
            </div>
          {:else if imageError}
            <div class="error-container">
              <div class="error-icon">!</div>
              <p class="error-message">{imageError}</p>
            </div>
          {/if}
        </div>
        
        <!-- Metadata section -->
        <div class="metadata-section">
          <!-- Prompt -->
          {#if prompt}
            <div class="metadata-card">
              <div class="metadata-label">{$text('embeds.image_generate.prompt_label.text')}</div>
              <div class="metadata-value prompt-value">{prompt}</div>
            </div>
          {/if}
          
          <!-- Properties row -->
          <div class="properties-row">
            {#if modelDisplay}
              <div class="property">
                <span class="property-label">{$text('embeds.image_generate.model_label.text')}</span>
                <span class="property-value">{modelDisplay}</span>
              </div>
            {/if}
            
            {#if aspectRatio}
              <div class="property">
                <span class="property-label">{$text('embeds.image_generate.aspect_ratio.text')}</span>
                <span class="property-value">{aspectRatio}</span>
              </div>
            {/if}
            
            {#if resolutionDisplay}
              <div class="property">
                <span class="property-label">{$text('embeds.image_generate.resolution.text')}</span>
                <span class="property-value">{resolutionDisplay}</span>
              </div>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .image-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: auto;
  }
  
  /* Image section */
  .image-section {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 0;
    padding: 16px;
    background: var(--color-grey-5, #fafafa);
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
    border-radius: 8px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  }
  
  /* Loading state */
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
  
  /* Error */
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
  
  /* Metadata section */
  .metadata-section {
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    border-top: 1px solid var(--color-grey-15, #f0f0f0);
  }
  
  .metadata-card {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .metadata-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--color-grey-50, #888);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .metadata-value {
    font-size: 14px;
    color: var(--color-grey-90, #1a1a1a);
    line-height: 1.5;
  }
  
  .prompt-value {
    padding: 10px 12px;
    background: var(--color-grey-5, #fafafa);
    border-radius: 6px;
    border-left: 3px solid var(--color-app-images, #8B5CF6);
    white-space: pre-wrap;
    word-break: break-word;
  }
  
  /* Properties row */
  .properties-row {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
  }
  
  .property {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .property-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--color-grey-50, #888);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .property-value {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-grey-80, #333);
  }
  
  /* Dark mode */
  :global(.dark) .image-section {
    background: var(--color-grey-95, #111);
  }
  
  :global(.dark) .full-image {
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
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
  
  :global(.dark) .metadata-section {
    border-top-color: var(--color-grey-85, #252525);
  }
  
  :global(.dark) .metadata-value {
    color: var(--color-grey-20, #eaeaea);
  }
  
  :global(.dark) .prompt-value {
    background: var(--color-grey-90, #1a1a1a);
  }
  
  :global(.dark) .property-value {
    color: var(--color-grey-30, #ccc);
  }
  
  /* Responsive */
  @media (max-width: 768px) {
    .metadata-section {
      padding: 16px;
    }
    
    .properties-row {
      gap: 12px;
    }
    
    .image-section {
      padding: 8px;
    }
  }
</style>
