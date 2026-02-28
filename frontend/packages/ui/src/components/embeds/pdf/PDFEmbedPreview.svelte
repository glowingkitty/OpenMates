<!--
  frontend/packages/ui/src/components/embeds/pdf/PDFEmbedPreview.svelte

  Preview card for user-uploaded PDF embeds shown in the message input editor.

  Lifecycle states:
  - 'uploading'   → file is being uploaded to the server (credit charge + encryption)
  - 'processing'  → upload complete, background OCR is running (Mistral + pymupdf)
  - 'finished'    → OCR complete (delivered via WebSocket embed_update)
  - 'error'       → upload or processing failure

  Displays:
  - When finished + screenshot available: full-width page-1 screenshot image
    (same pattern as ImageEmbedPreview — decrypted client-side via AES-256-GCM)
  - Otherwise: single centered PDF icon (no duplicate icon — BasicInfosBar is hidden
    for this case and the icon fills the details area)

  Architecture:
  - Mounts inside the TipTap editor via PdfRenderer.ts.
  - Uses UnifiedEmbedPreview for layout, status bar, and the 3D hover effect.
  - screenshot_s3_keys + aes_key + aes_nonce come from the embed TOON content,
    delivered via onEmbedDataUpdated when the WS send_embed_data event is processed
    by UnifiedEmbedPreview.
  - showSkillIcon=false always — the PDF icon is rendered inside the details snippet.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { skillPreviewService } from '../../../services/skillPreviewService';
  import {
    fetchAndDecryptImage,
    getCachedImageUrl,
    retainCachedImage,
    releaseCachedImage,
  } from '../images/imageEmbedCrypto';

  /** Max display length for the filename in the card title (chars) */
  const MAX_FILENAME_LENGTH = 30;

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Original filename of the uploaded PDF */
    filename?: string;
    /** Current embed status */
    status: 'uploading' | 'processing' | 'finished' | 'error';
    /** Number of pages (available after successful upload) */
    pageCount?: number | null;
    /** Error message shown when status is 'error' */
    uploadError?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Called when the user clicks the stop button during upload */
    onStop?: () => void;
    /**
     * Called when the user clicks the embed card after it reaches 'finished' state.
     * ActiveChat.svelte handles this by mounting PDFEmbedFullscreen.svelte.
     */
    onFullscreen?: () => void;
  }

  let {
    id,
    filename,
    status: statusProp,
    pageCount,
    uploadError,
    isMobile = false,
    onStop,
    onFullscreen,
  }: Props = $props();

  let status = $derived(statusProp);

  // -------------------------------------------------------------------------
  // Screenshot image state (decrypted from S3 after OCR completes)
  // -------------------------------------------------------------------------

  /** S3 key for page 1 screenshot — populated via onEmbedDataUpdated */
  let screenshotS3Key = $state<string | undefined>(undefined);
  /** Plaintext AES-256 key (base64) — from embed TOON content */
  let aesKey = $state<string | undefined>(undefined);
  /** AES-GCM nonce (base64) — from embed TOON content */
  let aesNonce = $state<string | undefined>(undefined);

  /** Decrypted page-1 blob URL */
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);

  /** Track which S3 key we retained in the shared cache */
  let retainedS3Key: string | undefined = undefined;

  /** Max retries for S3 fetch */
  const MAX_LOAD_RETRIES = 3;
  let loadRetryCount = $state(0);

  // Lazy loading via IntersectionObserver
  let isInView = $state(false);
  let containerRef: HTMLElement | undefined = $state(undefined);
  let observer: IntersectionObserver | undefined = undefined;

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

  /**
   * Receive decoded TOON content from UnifiedEmbedPreview after the WS
   * send_embed_data event is processed. Extracts the page-1 screenshot S3
   * key and AES credentials needed to fetch the preview image.
   */
  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
  }): void {
    const content = data.decodedContent;
    const keys = content.screenshot_s3_keys as Record<string, string> | undefined;
    const key = keys?.['1'];
    if (key) {
      screenshotS3Key = key;
    }
    const k = content.aes_key as string | undefined;
    const n = content.aes_nonce as string | undefined;
    if (k) aesKey = k;
    if (n) aesNonce = n;
  }

  // Fetch page-1 screenshot once key + credentials become available and embed is in view
  $effect(() => {
    if (
      isInView &&
      status === 'finished' &&
      screenshotS3Key &&
      aesKey &&
      aesNonce &&
      !imageUrl &&
      !isLoadingImage &&
      !imageError
    ) {
      loadScreenshot();
    }
  });

  async function loadScreenshot(): Promise<void> {
    if (!screenshotS3Key || !aesKey || !aesNonce) return;
    if (imageUrl) return;
    if (loadRetryCount >= MAX_LOAD_RETRIES) {
      console.warn('[PDFEmbedPreview] Giving up after max retries:', screenshotS3Key);
      return;
    }

    // Check shared cache first
    const cached = getCachedImageUrl(screenshotS3Key);
    if (cached) {
      imageUrl = cached;
      if (retainedS3Key && retainedS3Key !== screenshotS3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = screenshotS3Key;
      retainCachedImage(screenshotS3Key);
      return;
    }

    loadRetryCount += 1;
    isLoadingImage = true;
    imageError = undefined;

    try {
      console.debug(`[PDFEmbedPreview] Loading page-1 screenshot (attempt ${loadRetryCount}):`, screenshotS3Key);
      // s3BaseUrl not needed — fetchAndDecryptImage uses presigned URL service
      const blob = await fetchAndDecryptImage('', screenshotS3Key, aesKey, aesNonce);
      imageUrl = URL.createObjectURL(blob);
      if (retainedS3Key && retainedS3Key !== screenshotS3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = screenshotS3Key;
      retainCachedImage(screenshotS3Key);
      console.debug('[PDFEmbedPreview] Page-1 screenshot loaded');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('[PDFEmbedPreview] Failed to load screenshot:', msg);
      imageError = 'Preview unavailable';
    } finally {
      isLoadingImage = false;
    }
  }

  onDestroy(() => {
    if (retainedS3Key) {
      releaseCachedImage(retainedS3Key);
      retainedS3Key = undefined;
    }
    observer?.disconnect();
    skillPreviewService.removeEventListener('skillPreviewUpdate', handleSkillPreviewUpdate);
  });

  // -------------------------------------------------------------------------
  // "Viewing…" state — while pdf.view skill is running on this embed
  // -------------------------------------------------------------------------

  let isBeingViewed = $state(false);

  function handleSkillPreviewUpdate(event: Event): void {
    const customEvent = event as CustomEvent;
    const { previewData } = customEvent.detail || {};
    if (!previewData) return;
    if (previewData.app_id !== 'pdf' || previewData.skill_id !== 'view') return;
    const embedId = (previewData as Record<string, unknown>).embed_id as string | undefined;
    if (embedId && embedId !== id) return;
    isBeingViewed = previewData.status === 'processing';
  }

  skillPreviewService.addEventListener('skillPreviewUpdate', handleSkillPreviewUpdate);

  // -------------------------------------------------------------------------
  // Derived display state
  // -------------------------------------------------------------------------

  /**
   * Map upload-specific status to the UnifiedEmbedPreview status union.
   * 'uploading' → 'processing' (shows the animated spinner in the card).
   */
  let unifiedStatus = $derived(
    isBeingViewed ? 'processing'
    : status === 'uploading' ? 'processing'
    : (status as 'processing' | 'finished' | 'error'),
  );

  /** Whether a screenshot image is ready to display */
  let hasImage = $derived(!!imageUrl && !imageError);

  /** Card title: truncated filename */
  let skillName = $derived.by(() => {
    if (!filename) return 'PDF';
    if (filename.length > MAX_FILENAME_LENGTH) {
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
    }
    return filename;
  });

  /**
   * Card subtitle:
   * - 'viewing'    → "Viewing…"
   * - 'uploading'  → "Uploading…"
   * - 'processing' → "Processing N pages…" or "Processing…"
   * - 'finished'   → "N page(s)" (or plain "PDF")
   * - 'error'      → error message
   */
  let statusText = $derived.by(() => {
    if (isBeingViewed) return $text('app_skills.pdf.view.viewing');
    if (status === 'uploading') return $text('app_skills.pdf.view.uploading');
    if (status === 'error') return uploadError || $text('app_skills.pdf.view.upload_failed');
    if (status === 'processing') {
      if (pageCount && pageCount > 0) {
        return $text('app_skills.pdf.view.processing_pages', { values: { count: pageCount } });
      }
      return $text('app_skills.pdf.view.processing');
    }
    if (status === 'finished') {
      if (pageCount && pageCount > 0) {
        return pageCount === 1 ? '1 page' : `${pageCount} pages`;
      }
      return $text('app_skills.pdf.view');
    }
    return '';
  });

  let showStop = $derived((status === 'uploading' || status === 'processing') && !!onStop);
  let handleFullscreen = $derived(status === 'finished' ? onFullscreen : undefined);
</script>

<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="read"
  skillIconName="pdf"
  status={unifiedStatus}
  {skillName}
  {isMobile}
  onStop={showStop ? onStop : undefined}
  onFullscreen={handleFullscreen}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  hasFullWidthImage={hasImage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="pdf-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>

      {#if hasImage}
        <!--
          Page-1 screenshot available: show full-bleed like ImageEmbedPreview.
          Clicking opens the fullscreen viewer (cursor: zoom-in).
        -->
        <div
          class="image-content"
          class:clickable={status === 'finished' && !!handleFullscreen}
        >
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions a11y_click_events_have_key_events -->
          <img
            src={imageUrl}
            alt={filename || 'PDF page 1'}
            class="preview-image"
            onclick={status === 'finished' ? handleFullscreen : undefined}
          />
        </div>

      {:else}
        <!--
          No screenshot yet (uploading / processing / error / screenshot not loaded).
          Show a single centered PDF icon — no filename text here since the
          BasicInfosBar below already shows the name + status.
        -->
        <div class="pdf-icon-center">
          <div class="icon_rounded pdf"></div>
        </div>
      {/if}

    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .pdf-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  /* Full-bleed screenshot — mirrors ImageEmbedPreview */
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
    transition: opacity 0.15s ease;
  }

  .image-content.clickable:hover .preview-image {
    opacity: 0.92;
  }

  /* Fallback: single centered PDF icon when no screenshot */
  .pdf-icon-center {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  .pdf-icon-center .icon_rounded {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    background-size: 26px 26px;
    background-repeat: no-repeat;
    background-position: center;
    flex-shrink: 0;
  }

  /* Dark mode */
  :global(.dark) .image-content {
    background: var(--color-grey-90, #1a1a1a);
  }
</style>
