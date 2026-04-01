<!--
  frontend/packages/ui/src/components/embeds/pdf/PDFEmbedFullscreen.svelte

  Fullscreen viewer for user-uploaded PDF embeds.

  Triggered when the user clicks a finished PDF embed card in the editor.

  Architecture:
  - Mounted by ActiveChat.svelte in response to the 'pdffullscreen' CustomEvent.
  - PdfRenderer.ts dispatches that event from the onFullscreen prop passed to
    PDFEmbedPreview.svelte (only active when status === 'finished').
  - The event carries embedId so this component can look up the TOON content
    from IndexedDB via resolveEmbed() + decodeToonContent().
  - TOON content contains: screenshot_s3_keys, aes_key, aes_nonce — all needed
    for client-side AES-256-GCM decryption of the encrypted PNG screenshots.
  - Screenshots are fetched via presigned URLs (private S3 bucket) and decrypted
    in the browser using the Web Crypto API — same pattern as ImageEmbedFullscreen.

  Display:
  - All pages shown as a scrollable vertical stack of decrypted screenshots.
  - Each page image is loaded lazily (IntersectionObserver).
  - Page number badge overlaid bottom-left on each image.
  - Fallback: if screenshots unavailable, shows filename + page count + hint to
    use AI to read or view the PDF.

  Event chain (triggered on embed card click):
    PDFEmbedPreview.svelte (onFullscreen prop)
    → PdfRenderer.ts (dispatches 'pdffullscreen' CustomEvent with embedId)
    → MessageInput.svelte (re-dispatches)
    → ActiveChat.svelte (handlePdfFullscreen → showPdfEmbedFullscreen = true)
    → this component is mounted with embedId
-->

<script lang="ts">
  import { onMount, onDestroy, untrack } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /** Max display length for the filename in the bottom bar title (chars) */
  const MAX_FILENAME_LENGTH = 40;

  interface Props {
    /** Embed ID used to look up screenshot_s3_keys + AES credentials from IndexedDB */
    embedId?: string;
    /** Original filename of the uploaded PDF (from TipTap node attrs — always available) */
    filename?: string;
    /** Number of pages in the PDF (from TipTap node attrs — available after upload) */
    pageCount?: number | null;
    /** Close handler */
    onClose: () => void;
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
    embedId,
    filename = 'document.pdf',
    pageCount,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection = null,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Embed content: screenshot keys + AES credentials for client-side decryption
  // ---------------------------------------------------------------------------

  /** Map page number (as string) → S3 key for that page's encrypted PNG */
  let screenshotS3Keys = $state<Record<string, string>>({});
  /** Plaintext base64 AES-256 key for decrypting screenshots */
  let aesKey = $state<string | undefined>(undefined);
  /** Base64 GCM nonce shared across all screenshots */
  let aesNonce = $state<string | undefined>(undefined);
  /** Whether embed content has been resolved */
  let contentLoaded = $state(false);
  /** Error loading embed content */
  let contentError = $state<string | undefined>(undefined);

  /** Derived page numbers sorted numerically */
  let pageNumbers = $derived(
    Object.keys(screenshotS3Keys)
      .map(Number)
      .sort((a, b) => a - b),
  );

  /** Whether we have screenshots to display.
   * aesNonce may be "" for new PDFs (nonce embedded per-artefact) so check !== undefined. */
  let hasScreenshots = $derived(pageNumbers.length > 0 && !!aesKey && aesNonce !== undefined);

  // ---------------------------------------------------------------------------
  // Per-page image state: decrypted blob URL + loading/error state
  // ---------------------------------------------------------------------------

  interface PageImageState {
    url: string | undefined;
    loading: boolean;
    error: string | undefined;
    retries: number;
  }

  /** Map page number → image state */
  let pageImages = $state<Record<number, PageImageState>>({});

  const MAX_PAGE_RETRIES = 2;

  /** Initialise empty state for each page when screenshotS3Keys loads */
  $effect(() => {
    if (!hasScreenshots) return;
    const next: Record<number, PageImageState> = {};
    for (const pn of pageNumbers) {
      // Preserve existing state for pages already loaded
      next[pn] = pageImages[pn] ?? { url: undefined, loading: false, error: undefined, retries: 0 };
    }
    pageImages = next;
  });

  // ---------------------------------------------------------------------------
  // Lazy loading: IntersectionObserver per page container
  // ---------------------------------------------------------------------------

  /** Set of page numbers currently in view (populated by IntersectionObserver) */
  let inViewPages = $state(new Set<number>());
  let pageContainers = $state<Record<number, HTMLElement>>({});
  let observers: IntersectionObserver[] = [];

  $effect(() => {
    // Disconnect existing observers before rebuilding
    for (const obs of observers) obs.disconnect();
    observers = [];

    for (const pn of pageNumbers) {
      const el = pageContainers[pn];
      if (!el) continue;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries[0]?.isIntersecting) {
            inViewPages = new Set([...inViewPages, pn]);
            obs.disconnect();
          }
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      observers.push(obs);
    }

    return () => {
      for (const obs of observers) obs.disconnect();
      observers = [];
    };
  });

  // ---------------------------------------------------------------------------
  // Load page images when they enter view
  // ---------------------------------------------------------------------------

  $effect(() => {
    if (!hasScreenshots) return;
    for (const pn of inViewPages) {
      // Use untrack() to read pageImages without creating a reactive dependency.
      // Without this, writing pageImages inside loadPageImage re-triggers this
      // effect, causing an infinite effect_update_depth_exceeded loop.
      const state = untrack(() => pageImages[pn]);
      if (!state || state.url || state.loading || state.retries >= MAX_PAGE_RETRIES) continue;
      loadPageImage(pn);
    }
  });

  async function loadPageImage(pageNum: number): Promise<void> {
    const s3Key = screenshotS3Keys[String(pageNum)];
    // aesNonce may be "" for new PDFs (nonce embedded per-artefact); check !== undefined
    if (!s3Key || !aesKey || aesNonce === undefined) return;

    const state = pageImages[pageNum];
    if (!state || state.url || state.loading) return;

    pageImages = {
      ...pageImages,
      [pageNum]: { ...state, loading: true, error: undefined },
    };

    try {
      const { fetchAndDecryptImage } = await import('../images/imageEmbedCrypto');
      // s3BaseUrl not needed — fetchAndDecryptImage uses the presigned URL service
      const blob = await fetchAndDecryptImage('', s3Key, aesKey, aesNonce);
      const url = URL.createObjectURL(blob);
      pageImages = {
        ...pageImages,
        [pageNum]: { url, loading: false, error: undefined, retries: (pageImages[pageNum]?.retries ?? 0) },
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`[PDFEmbedFullscreen] Failed to load page ${pageNum}:`, msg);
      const currentState = pageImages[pageNum];
      pageImages = {
        ...pageImages,
        [pageNum]: {
          url: undefined,
          loading: false,
          error: 'Page unavailable',
          retries: (currentState?.retries ?? 0) + 1,
        },
      };
    }
  }

  // ---------------------------------------------------------------------------
  // Fetch embed content from IndexedDB / server on mount
  // ---------------------------------------------------------------------------

  onMount(async () => {
    if (!embedId) {
      // No embed ID — fall back to icon + hint display
      contentLoaded = true;
      return;
    }
    try {
      const { resolveEmbed, decodeToonContent } = await import('../../../services/embedResolver');
      const embedData = await resolveEmbed(embedId);
      if (!embedData?.content) {
        console.warn('[PDFEmbedFullscreen] No embed content found for:', embedId);
        contentLoaded = true;
        return;
      }
      const decoded = await decodeToonContent(embedData.content) as Record<string, unknown>;
      const keys = decoded.screenshot_s3_keys as Record<string, string> | undefined;
      if (keys && typeof keys === 'object') screenshotS3Keys = keys;
      const k = decoded.aes_key as string | undefined;
      // aes_nonce is "" for new PDFs (nonce embedded per-artefact); treat undefined vs "" distinctly
      const n = decoded.aes_nonce as string | undefined;
      if (k) aesKey = k;
      if (n !== undefined) aesNonce = n;
      // Prefer decoded page_count over the prop (more accurate)
      const decodedPageCount = decoded.page_count as number | undefined;
      if (decodedPageCount && !pageCount) pageCount = decodedPageCount;
      console.debug('[PDFEmbedFullscreen] Loaded embed content:', {
        pages: Object.keys(screenshotS3Keys).length,
        hasKey: !!aesKey,
      });
    } catch (err) {
      console.error('[PDFEmbedFullscreen] Failed to load embed content:', err);
      contentError = 'Could not load PDF preview';
    } finally {
      contentLoaded = true;
    }
  });

  onDestroy(() => {
    // Revoke all blob URLs to free memory
    for (const state of Object.values(pageImages)) {
      if (state.url) URL.revokeObjectURL(state.url);
    }
    for (const obs of observers) obs.disconnect();
  });

  // ---------------------------------------------------------------------------
  // Header info (bottom bar of UnifiedEmbedFullscreen)
  // ---------------------------------------------------------------------------

  let infoBarTitle = $derived.by(() => {
    if (!filename) return 'PDF';
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

  let infoBarSubtitle = $derived.by(() => {
    if (pageCount && pageCount > 0) {
      return pageCount === 1 ? '1 page' : `${pageCount} pages`;
    }
    return $text('common.pdf');
  });
</script>

<UnifiedEmbedFullscreen
  appId="pdf"
  skillId="view"
  skillIconName="pdf"
  embedHeaderTitle={infoBarTitle}
  embedHeaderSubtitle={infoBarSubtitle}
  showShare={false}
  {onClose}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="pdf-fullscreen-content" data-testid="pdf-fullscreen-content">

      {#if !contentLoaded}
        <!-- Loading embed content -->
        <div class="pdf-loading-state">
          <div class="pdf-spinner" data-testid="pdf-spinner"></div>
          <p class="pdf-hint">Loading pages…</p>
        </div>

      {:else if hasScreenshots}
        <!--
          Screenshots available: render all pages as a scrollable vertical stack.
          Each page uses an IntersectionObserver for lazy loading.
        -->
        <div class="pdf-pages-scroll">
          {#each pageNumbers as pageNum (pageNum)}
            <div
              class="pdf-page-container"
              bind:this={pageContainers[pageNum]}
            >
              {#if pageImages[pageNum]?.url}
                <img
                  src={pageImages[pageNum].url}
                  alt={`Page ${pageNum} of ${filename}`}
                  class="pdf-page-image"
                  data-testid="pdf-page-image"
                  loading="lazy"
                />
                <span class="pdf-page-badge">{pageNum}</span>
              {:else if pageImages[pageNum]?.loading}
                <div class="pdf-page-skeleton">
                  <div class="pdf-spinner small"></div>
                </div>
              {:else if pageImages[pageNum]?.error}
                <div class="pdf-page-skeleton error">
                  <span class="pdf-hint small">{pageImages[pageNum].error}</span>
                </div>
              {:else}
                <!-- Not yet in view — show skeleton placeholder -->
                <div class="pdf-page-skeleton"></div>
              {/if}
            </div>
          {/each}
        </div>

      {:else}
        <!--
          No screenshots available (processing still running, or older PDF
          uploaded before screenshot support was added). Show icon + hint.
        -->
        <div class="pdf-info-fallback" data-testid="pdf-info-fallback">
          <div class="pdf-icon-wrapper">
            <div class="icon_rounded pdf large"></div>
          </div>
          <h2 class="pdf-filename" title={filename}>{infoBarTitle}</h2>
          {#if pageCount && pageCount > 0}
            <p class="pdf-pages">{infoBarSubtitle}</p>
          {/if}
          {#if contentError}
            <p class="pdf-hint error">{contentError}</p>
          {:else}
            <p class="pdf-hint">
              Ask the AI to read, search, or view pages of this PDF.
            </p>
          {/if}
        </div>
      {/if}

    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ==========================================================================
     Outer wrapper — fills the content area provided by UnifiedEmbedFullscreen
     ========================================================================== */

  .pdf-fullscreen-content {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }

  /* ==========================================================================
     Loading / fallback states (centered)
     ========================================================================== */

  .pdf-loading-state,
  .pdf-info-fallback {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-height: 300px;
    padding: 60px 40px 80px;
    box-sizing: border-box;
    gap: 16px;
    text-align: center;
    flex: 1;
  }

  /* ==========================================================================
     Scrollable page stack
     ========================================================================== */

  .pdf-pages-scroll {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 24px;
    overflow-y: auto;
    overflow-x: hidden;
    width: 100%;
    height: 100%;
    padding: 24px 16px 40px;
    box-sizing: border-box;
  }

  /* ==========================================================================
     Individual page container
     ========================================================================== */

  .pdf-page-container {
    position: relative;
    width: 100%;
    max-width: 800px;
    border-radius: 8px;
    overflow: hidden;
    background: var(--color-grey-10, #f5f5f5);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12);
    flex-shrink: 0;
  }

  .pdf-page-image {
    display: block;
    width: 100%;
    height: auto;
    object-fit: contain;
  }

  /* Page number badge — overlaid bottom-left on each screenshot */
  .pdf-page-badge {
    position: absolute;
    bottom: 8px;
    left: 8px;
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 7px;
    border-radius: 20px;
    pointer-events: none;
    user-select: none;
  }

  /* Skeleton placeholder while page is not yet loaded */
  .pdf-page-skeleton {
    width: 100%;
    /* A4 aspect ratio approx */
    padding-bottom: 141.4%;
    background: var(--color-grey-15, #ebebeb);
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
  }

  .pdf-page-skeleton > * {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
  }

  .pdf-page-skeleton.error {
    background: var(--color-grey-10, #f5f5f5);
  }

  /* ==========================================================================
     Spinner
     ========================================================================== */

  .pdf-spinner {
    width: 28px;
    height: 28px;
    border: 3px solid var(--color-grey-20, #ddd);
    border-top-color: var(--color-app-pdf, #e74c3c);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  .pdf-spinner.small {
    width: 20px;
    height: 20px;
    border-width: 2px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ==========================================================================
     Text elements (fallback / info state)
     ========================================================================== */

  .pdf-icon-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 8px;
  }

  .icon_rounded.large {
    width: 80px;
    height: 80px;
    border-radius: 20px;
    background-size: 40px 40px;
    background-repeat: no-repeat;
    background-position: center;
  }

  .pdf-filename {
    font-size: 20px;
    font-weight: 600;
    color: var(--color-font-primary);
    margin: 0;
    word-break: break-word;
    max-width: 600px;
  }

  .pdf-pages {
    font-size: 15px;
    color: var(--color-grey-60, #888);
    margin: 0;
  }

  .pdf-hint {
    font-size: 14px;
    color: var(--color-grey-50, #999);
    margin: 8px 0 0;
    max-width: 380px;
    line-height: 1.5;
  }

  .pdf-hint.error {
    color: var(--color-danger, #e74c3c);
  }

  .pdf-hint.small {
    font-size: 12px;
    margin: 0;
    max-width: none;
  }

  /* ==========================================================================
     Dark mode
     ========================================================================== */

  :global(.dark) .pdf-page-container {
    background: var(--color-grey-90, #1a1a1a);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  }

  :global(.dark) .pdf-page-skeleton {
    background: var(--color-grey-80, #2a2a2a);
  }

  :global(.dark) .pdf-page-skeleton.error {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .pdf-filename {
    color: var(--color-font-primary-dark, #e0e0e0);
  }

  :global(.dark) .pdf-pages,
  :global(.dark) .pdf-hint {
    color: var(--color-grey-40, #999);
  }
</style>
