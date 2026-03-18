<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfViewEmbedPreview.svelte

  Preview card for the pdf/view skill result embed.
  Shown when the AI executes the pdf.view skill to view specific PDF pages.

  Displays:
  - Processing state: PDF icon centered (same as PDFEmbedPreview during OCR)
  - Finished state: decrypted page-1 screenshot image from the original PDF upload embed
    (full-bleed, same as PDFEmbedPreview in finished state)
  - Error state: centered icon

  On click: opens the ORIGINAL uploaded PDF's fullscreen viewer
  (fires 'pdffullscreen' CustomEvent with the upload embed's data).

  Architecture:
  - Mounted by AppSkillUseRenderer.ts when app_id='pdf' and skill_id='view'.
  - originalEmbedId prop: the embed_id of the original PDF upload embed.
  - On mount (when originalEmbedId is set and status is finished):
    resolves the original upload embed via resolveEmbed() + decodeToonContent(),
    extracts screenshot_s3_keys['1'] + aes_key + aes_nonce,
    then decrypts the image via fetchAndDecryptImage — same as PDFEmbedPreview.
  - showSkillIcon=false so the screenshot (or icon) fills the entire details area.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { resolveEmbed, decodeToonContent } from '../../../services/embedResolver';
  import {
    fetchAndDecryptImage,
    getCachedImageUrl,
    retainCachedImage,
    releaseCachedImage,
  } from '../images/imageEmbedCrypto';

  interface Props {
    /** Unique embed ID for this skill-use embed */
    id: string;
    /** Filename of the PDF (from original upload embed) */
    filename?: string;
    /** Total page count of the PDF */
    pageCount?: number;
    /** Pages viewed by this skill call (e.g. [1, 2, 3]) */
    pages?: number[];
    /** embed_id of the ORIGINAL uploaded PDF — needed to resolve the screenshot */
    originalEmbedId?: string;
    /** Processing status of the skill execution */
    status: 'processing' | 'finished' | 'error';
    /** Error message if skill failed */
    error?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /**
     * Called when the user clicks to open fullscreen.
     * Implemented by AppSkillUseRenderer: resolves original upload embed
     * and fires 'pdffullscreen' CustomEvent.
     */
    onFullscreen: () => void;
  }

  let {
    id,
    filename,
    pageCount,
    pages,
    originalEmbedId,
    status: statusProp,
    error,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Local state — updated via onEmbedDataUpdated and screenshot loading
  // ---------------------------------------------------------------------------

  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localOriginalEmbedId = $state<string>('');

  $effect(() => {
    localStatus = statusProp;
    localOriginalEmbedId = originalEmbedId || '';
  });

  // ---------------------------------------------------------------------------
  // Screenshot image state (same pattern as PDFEmbedPreview)
  // ---------------------------------------------------------------------------

  let screenshotS3Key = $state<string | undefined>(undefined);
  let aesKey = $state<string | undefined>(undefined);
  let aesNonce = $state<string | undefined>(undefined);
  let imageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  let retainedS3Key: string | undefined = undefined;
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

  // ---------------------------------------------------------------------------
  // Resolve original upload embed to get screenshot credentials
  // ---------------------------------------------------------------------------

  let resolvedEmbedId = $state<string>('');  // tracks which embedId we already resolved

  /**
   * Resolve the original upload embed and extract screenshot S3 key + AES creds.
   * Called when originalEmbedId becomes available and status is finished.
   */
  async function resolveScreenshotCredentials(embedId: string): Promise<void> {
    if (!embedId || resolvedEmbedId === embedId) return;
    resolvedEmbedId = embedId;

    try {
      const uploadEmbed = await resolveEmbed(embedId);
      if (!uploadEmbed) {
        console.warn('[PdfViewEmbedPreview] Could not resolve original PDF embed:', embedId);
        return;
      }
      const uploadContent = uploadEmbed.content
        ? await decodeToonContent(uploadEmbed.content)
        : null;
      if (!uploadContent) {
        console.warn('[PdfViewEmbedPreview] Original embed has no decoded content:', embedId);
        return;
      }

      // Extract screenshot credentials (same as PDFEmbedPreview.handleEmbedDataUpdated)
      const keys = uploadContent.screenshot_s3_keys as Record<string, string> | undefined;
      const key = keys?.['1'];
      if (key) screenshotS3Key = key;
      const k = uploadContent.aes_key as string | undefined;
      // aes_nonce is "" for new PDFs (nonce embedded per-artefact); treat undefined vs "" distinctly
      const n = uploadContent.aes_nonce as string | undefined;
      if (k) aesKey = k;
      if (n !== undefined) aesNonce = n;

      console.debug('[PdfViewEmbedPreview] Resolved screenshot credentials for:', embedId, {
        hasS3Key: !!key,
        hasAesKey: !!k,
        hasAesNonce: n !== undefined,
      });
    } catch (err) {
      console.error('[PdfViewEmbedPreview] Error resolving original PDF embed:', err);
    }
  }

  // Trigger resolution when embedId + finished status are available
  $effect(() => {
    if (localStatus === 'finished' && localOriginalEmbedId) {
      resolveScreenshotCredentials(localOriginalEmbedId);
    }
  });

  // Trigger screenshot load once all credentials + in-view.
  // aesNonce may be "" for new PDFs (nonce embedded per-artefact); check !== undefined.
  $effect(() => {
    if (
      isInView &&
      localStatus === 'finished' &&
      screenshotS3Key &&
      aesKey &&
      aesNonce !== undefined &&
      !imageUrl &&
      !isLoadingImage &&
      !imageError
    ) {
      loadScreenshot();
    }
  });

  async function loadScreenshot(): Promise<void> {
    if (!screenshotS3Key || !aesKey || aesNonce === undefined) return;
    if (imageUrl) return;
    if (loadRetryCount >= MAX_LOAD_RETRIES) {
      console.warn('[PdfViewEmbedPreview] Giving up after max retries:', screenshotS3Key);
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
      console.debug(`[PdfViewEmbedPreview] Loading page-1 screenshot (attempt ${loadRetryCount}):`, screenshotS3Key);
      const blob = await fetchAndDecryptImage('', screenshotS3Key, aesKey, aesNonce);
      imageUrl = URL.createObjectURL(blob);
      if (retainedS3Key && retainedS3Key !== screenshotS3Key) releaseCachedImage(retainedS3Key);
      retainedS3Key = screenshotS3Key;
      retainCachedImage(screenshotS3Key);
      console.debug('[PdfViewEmbedPreview] Page-1 screenshot loaded');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('[PdfViewEmbedPreview] Failed to load screenshot:', msg);
      imageError = 'Preview unavailable';
    } finally {
      isLoadingImage = false;
    }
  }

  // ---------------------------------------------------------------------------
  // onEmbedDataUpdated — receive live updates from UnifiedEmbedPreview
  // ---------------------------------------------------------------------------

  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
  }): void {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status as 'processing' | 'finished' | 'error';
    }
    // If the original embed ID is embedded in the skill result content
    const c = data.decodedContent;
    const eid = c?.embed_id as string | undefined;
    if (eid && !localOriginalEmbedId) localOriginalEmbedId = eid;
  }

  onDestroy(() => {
    if (retainedS3Key) {
      releaseCachedImage(retainedS3Key);
      retainedS3Key = undefined;
    }
    observer?.disconnect();
  });

  // ---------------------------------------------------------------------------
  // Derived display state
  // ---------------------------------------------------------------------------

  let skillName = $derived($text('app_skills.pdf.view.skill_name'));

  let statusText = $derived.by(() => {
    if (localStatus === 'processing') return $text('app_skills.pdf.view.viewing') || 'Viewing\u2026';
    if (localStatus === 'error') return error || '';
    if (localStatus === 'finished') {
      const pcStr = pageCount && pageCount > 0
        ? (pageCount === 1 ? '1 page' : `${pageCount} pages`)
        : '';
      if (pages && pages.length > 0) {
        const sorted = [...pages].sort((a, b) => a - b);
        const pagesStr = sorted.length === 1
          ? `Page ${sorted[0]}`
          : `Pages ${sorted[0]}\u2013${sorted[sorted.length - 1]}`;
        return pcStr ? `${pagesStr} \u00B7 ${pcStr}` : pagesStr;
      }
      return pcStr || $text('app_skills.pdf.view');
    }
    return '';
  });

  let hasImage = $derived(!!imageUrl && !imageError);
  let isFullscreenEnabled = $derived(localStatus === 'finished' && !!onFullscreen);
</script>

<!--
  showSkillIcon=false so the screenshot (or icon) fills the entire details area,
  matching the visual pattern of the original PDFEmbedPreview card.
  hasFullWidthImage mirrors what PDFEmbedPreview passes to UnifiedEmbedPreview.
-->
<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="view"
  skillIconName="visible"
  status={localStatus}
  {skillName}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  hasFullWidthImage={hasImage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="pdf-view-preview" class:mobile={isMobileSnippet} bind:this={containerRef}>
      {#if hasImage}
        <!--
          Page-1 screenshot: full-bleed image, same as PDFEmbedPreview finished state.
          Clicking opens the original PDF fullscreen viewer.
        -->
        <div
          class="image-content"
          class:clickable={localStatus === 'finished' && isFullscreenEnabled}
        >
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions a11y_click_events_have_key_events -->
          <img
            src={imageUrl}
            alt={filename || 'PDF page 1'}
            class="preview-image"
            onclick={localStatus === 'finished' ? onFullscreen : undefined}
          />
        </div>
      {:else}
        <!--
          No screenshot: centered view (eye) icon while loading or on error.
        -->
        <div class="icon-center">
          <div class="icon_rounded visible"></div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .pdf-view-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  /* Full-bleed screenshot — mirrors PDFEmbedPreview */
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

  /* Fallback: centered icon */
  .icon-center {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  .icon-center .icon_rounded {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    background-size: 26px 26px;
    background-repeat: no-repeat;
    background-position: center;
    flex-shrink: 0;
    background-color: var(--color-grey-20);
  }

  /* Skill icon: visible.svg for pdf.view */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="visible"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/visible.svg');
    mask-image: url('@openmates/ui/static/icons/visible.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="visible"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/visible.svg');
    mask-image: url('@openmates/ui/static/icons/visible.svg');
  }

  /* Dark mode */
  :global(.dark) .image-content {
    background: var(--color-grey-90, #1a1a1a);
  }
</style>
