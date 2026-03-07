<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedFullscreen.svelte

  Fullscreen view for Document embeds (document_html).
  Uses UnifiedEmbedFullscreen as base and provides document-specific content.

  Architecture: See docs/claude/embed-types.md for the unified embed pattern.

  Designed to look like reading a document in Microsoft Word / Google Docs:
  - Dark grey background canvas (the area around and between pages)
  - White A4-sized pages centered with shadow (like printed pages)
  - Content flows naturally; grey gaps appear between pages
  - Floating zoom controls at the bottom (−, %, +)
  - Filename shown in header (e.g., "Report.docx")
  - Copy (plain text), Download (as .docx), Share actions

  Page rendering approach:
  We render content once in a fixed-width container matching A4 dimensions.
  After measuring, we insert invisible "spacer" elements into the DOM at
  page-break Y positions. Each spacer pushes subsequent content past the
  grey gap area. The background gradient draws the page/gap pattern, and
  the spacers keep text aligned to page content areas.

  Mobile rendering:
  Instead of breaking the A4 layout on narrow screens, we keep the exact
  same page structure and auto-calculate a zoom level that fits the
  container width. This ensures the document always looks like an actual
  A4 page, regardless of viewport size.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import {
    sanitizeDocumentHtml,
    stripHtmlTags,
    countDocWords,
    extractDocumentTitle,
    extractDocumentFilename,
    generateFilenameFromTitle
  } from './docsEmbedContent';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import type { PIIMapping } from '../../../types/chat';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { hydrateEmbedLinks, replaceEmbedRefsWithUrls, replaceEmbedRefsWithUrlsInHtml } from '../../../utils/embedLinkUtils';

  /**
   * Props for document embed fullscreen
   */
  interface Props {
    /** Document HTML content */
    htmlContent: string;
    /** Document title */
    title?: string;
    /** Document filename (e.g. "Report.docx") */
    filename?: string;
    /** Word count */
    wordCount?: number;
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
    /** Direction of navigation ('previous' | 'next') — set transiently during prev/next transitions */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" button to restore chat visibility (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
    /**
     * PII mappings from the parent chat — maps placeholder strings (e.g. "[EMAIL_1]")
     * to original values. When provided and piiRevealed is true, placeholder strings
     * in the document content are replaced with the originals for display.
     */
    piiMappings?: PIIMapping[];
    /**
     * Whether PII originals are currently visible.
     * When false (default), placeholder strings like [EMAIL_1] are shown as-is.
     * When true, placeholders are replaced with original values.
     * This is the initial value — the user can toggle locally in fullscreen.
     */
    piiRevealed?: boolean;
  }

  let {
    htmlContent,
    title,
    filename,
    wordCount = 0,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    piiMappings = [],
    piiRevealed = false
  }: Props = $props();

  // Local PII reveal toggle — initialised from prop but user can flip it in fullscreen.
  let localPiiRevealed = $state(false);

  // Keep localPiiRevealed in sync when the parent prop changes (e.g. user toggles in chat).
  $effect(() => {
    localPiiRevealed = piiRevealed;
  });

  /** Whether there are any PII mappings to apply (controls button visibility) */
  let hasPII = $derived(piiMappings.length > 0);

  function togglePII() {
    localPiiRevealed = !localPiiRevealed;
  }

  /**
   * Apply PII masking to the raw HTML string before sanitizing.
   * When localPiiRevealed is true, we restore originals so the user can read the full content.
   * When false, placeholders remain as-is (privacy mode).
   */
  let piiProcessedHtml = $derived.by(() => {
    if (!hasPII || !htmlContent) return htmlContent;
    if (localPiiRevealed) {
      return restorePIIInText(htmlContent, piiMappings);
    } else {
      return replacePIIOriginalsWithPlaceholders(htmlContent, piiMappings);
    }
  });

  // Sanitize HTML content for safe rendering (DOMPurify)
  let sanitizedHtml = $derived(sanitizeDocumentHtml(piiProcessedHtml));

  // Extract title from content if not provided
  let displayTitle = $derived.by(() => {
    if (title) return title;
    return extractDocumentTitle(htmlContent) || $text('embeds.document_snippet');
  });

  // Extract or generate filename for display
  let displayFilename = $derived.by(() => {
    if (filename) return filename;
    const extracted = extractDocumentFilename(htmlContent);
    if (extracted) return extracted;
    return generateFilenameFromTitle(displayTitle);
  });

  // Calculate word count from content if not provided
  let actualWordCount = $derived.by(() => {
    if (wordCount > 0) return wordCount;
    return countDocWords(htmlContent);
  });

  // Build status text: word count
  let statusText = $derived.by(() => {
    const wc = actualWordCount;
    if (wc === 0) return '';

    const wordText = wc === 1
      ? $text('embeds.document_word_singular')
      : $text('embeds.document_word_plural');

    return `${wc} ${wordText}`;
  });

  // Icon for documents
  const skillIconName = 'docs';

  // =============================================
  // A4 Page Dimensions (at 96 DPI)
  // =============================================
  // A4: 210mm × 297mm = 794 × 1123 px at 96 DPI
  // Page margin: 96px top/bottom (1 inch), 72px left/right (~0.75 inch — Word default)
  // Usable content height per page: 1123 - 96 - 96 = 931px
  // Usable content width per page: 794 - 72 - 72 = 650px
  // Gap between pages: 32px (grey canvas visible)
  // At each page break, spacer height = bottom margin + gap + top margin = 96 + 32 + 96 = 224px
  const PAGE_WIDTH = 794;
  const PAGE_CONTENT_HEIGHT = 931;
  const PAGE_GAP = 32;
  const PAGE_MARGIN_Y = 96;
  const SPACER_HEIGHT = PAGE_MARGIN_Y + PAGE_GAP + PAGE_MARGIN_Y; // 224px

  // =============================================
  // Zoom State
  // =============================================
  // Zoom levels include 25% for very small screens. Default is determined
  // by auto-fit calculation on mount, falling back to 75% on desktop.
  const ZOOM_LEVELS = [25, 50, 75, 100, 125, 150, 200];
  const DEFAULT_DESKTOP_ZOOM_INDEX = 2; // 75%
  let zoomIndex = $state(DEFAULT_DESKTOP_ZOOM_INDEX);
  let zoomLevel = $derived(ZOOM_LEVELS[zoomIndex]);
  /** Whether the initial auto-fit zoom has been calculated */
  let zoomInitialized = $state(false);

  function zoomIn() {
    if (zoomIndex < ZOOM_LEVELS.length - 1) {
      zoomIndex++;
    }
  }

  function zoomOut() {
    if (zoomIndex > 0) {
      zoomIndex--;
    }
  }

  /** Reset zoom to the auto-fit level for the current container width */
  function resetZoom() {
    zoomIndex = calculateFitZoomIndex();
  }

  /**
   * Calculate the zoom index that best fits the page width to the container.
   * Adds horizontal padding (48px total) so the page doesn't touch edges.
   */
  function calculateFitZoomIndex(): number {
    if (!canvasScrollEl) return DEFAULT_DESKTOP_ZOOM_INDEX;

    const CANVAS_HORIZONTAL_PADDING = 48;
    const availableWidth = canvasScrollEl.clientWidth - CANVAS_HORIZONTAL_PADDING;
    const fitRatio = availableWidth / PAGE_WIDTH;
    const fitPercent = Math.floor(fitRatio * 100);

    // Find the largest zoom level that fits, or use the smallest if none fit
    let bestIndex = 0;
    for (let i = ZOOM_LEVELS.length - 1; i >= 0; i--) {
      if (ZOOM_LEVELS[i] <= fitPercent) {
        bestIndex = i;
        break;
      }
    }
    return bestIndex;
  }

  // =============================================
  // DOM References
  // =============================================
  let contentEl: HTMLDivElement | undefined = $state(undefined);
  let canvasScrollEl: HTMLDivElement | undefined = $state(undefined);
  let pageCount = $state(1);

  // CSS class for injected spacers so we can identify and remove them
  const SPACER_CLASS = 'doc-page-break-spacer';

  // =============================================
  // Auto-fit zoom on mount and container resize
  // =============================================
  onMount(() => {
    // Calculate initial zoom after the DOM is ready
    const raf = requestAnimationFrame(() => {
      zoomIndex = calculateFitZoomIndex();
      zoomInitialized = true;
    });

    // Re-calculate when the container resizes (e.g. window resize, split view)
    let resizeObserver: ResizeObserver | undefined;
    if (canvasScrollEl) {
      resizeObserver = new ResizeObserver(() => {
        // Only auto-adjust if zoom hasn't been initialized yet
        if (!zoomInitialized) {
          zoomIndex = calculateFitZoomIndex();
          zoomInitialized = true;
        }
      });
      resizeObserver.observe(canvasScrollEl);
    }

    return () => {
      cancelAnimationFrame(raf);
      resizeObserver?.disconnect();
    };
  });

  // =============================================
  // Embed Inline Link Hydration
  // =============================================
  $effect(() => {
    void sanitizedHtml;
    if (!contentEl) return;
    const raf = requestAnimationFrame(() => {
      if (!contentEl) return;
      embedLinkCleanup = hydrateEmbedLinks(contentEl);
    });
    return () => {
      cancelAnimationFrame(raf);
      if (embedLinkCleanup) {
        embedLinkCleanup();
        embedLinkCleanup = undefined;
      }
    };
  });
  let embedLinkCleanup: (() => void) | undefined;

  // =============================================
  // Page Break Spacer Injection
  // =============================================
  // After content renders, we walk the DOM to find which elements
  // cross page boundaries, and insert spacer divs that push
  // subsequent content into the next page's content area.
  $effect(() => {
    if (!contentEl || !sanitizedHtml) {
      pageCount = 1;
      return;
    }

    const raf = requestAnimationFrame(() => {
      if (!contentEl) return;
      injectPageBreakSpacers();
    });

    return () => cancelAnimationFrame(raf);
  });

  /**
   * Measure the content and inject spacer divs at page boundaries.
   * Runs up to MAX_STABILIZATION_PASSES to handle cascading shifts
   * where inserting a spacer pushes content across another boundary.
   */
  function injectPageBreakSpacers() {
    if (!contentEl) return;

    const MAX_STABILIZATION_PASSES = 3;

    for (let pass = 0; pass < MAX_STABILIZATION_PASSES; pass++) {
      // Remove any previously injected spacers
      contentEl.querySelectorAll(`.${SPACER_CLASS}`).forEach(el => el.remove());

      // Measure the natural content height (without spacers)
      const naturalHeight = contentEl.scrollHeight;
      const numPages = Math.max(1, Math.ceil(naturalHeight / PAGE_CONTENT_HEIGHT));

      if (numPages <= 1) {
        pageCount = numPages;
        return;
      }

      // For each page break, find the child element that straddles the boundary
      // and insert a spacer before it. Work bottom-to-top so insertions don't
      // shift positions of earlier breaks.
      let insertedSpacers = 0;

      for (let breakIdx = numPages - 1; breakIdx >= 1; breakIdx--) {
        const breakY = breakIdx * PAGE_CONTENT_HEIGHT + insertedSpacers * SPACER_HEIGHT;

        const children = contentEl.children;
        let targetChild: Element | null = null;

        for (let c = 0; c < children.length; c++) {
          const child = children[c];
          if (child.classList.contains(SPACER_CLASS)) continue;

          const rect = child.getBoundingClientRect();
          const contentRect = contentEl.getBoundingClientRect();
          const childTop = rect.top - contentRect.top;
          const childBottom = childTop + rect.height;

          if (childBottom > breakY) {
            targetChild = child;
            break;
          }
        }

        if (targetChild) {
          const spacer = document.createElement('div');
          spacer.className = SPACER_CLASS;
          spacer.style.height = `${SPACER_HEIGHT}px`;
          spacer.style.flexShrink = '0';
          spacer.setAttribute('aria-hidden', 'true');

          contentEl.insertBefore(spacer, targetChild);
          insertedSpacers++;
        }
      }

      // Check if the page count is stable (no change from previous pass)
      const newHeight = contentEl.scrollHeight;
      const newPages = Math.max(1, Math.ceil((newHeight - insertedSpacers * SPACER_HEIGHT) / PAGE_CONTENT_HEIGHT));

      if (newPages === numPages) {
        pageCount = numPages;
        return;
      }

      // Page count changed — loop again to re-stabilize
      console.debug(`[DocsEmbedFullscreen] Spacer pass ${pass + 1}: pages ${numPages} -> ${newPages}, re-stabilizing`);
    }

    // After max passes, use whatever we have
    const finalSpacerCount = contentEl.querySelectorAll(`.${SPACER_CLASS}`).length;
    const finalHeight = contentEl.scrollHeight;
    pageCount = Math.max(1, Math.ceil((finalHeight - finalSpacerCount * SPACER_HEIGHT) / PAGE_CONTENT_HEIGHT));
  }

  // =============================================
  // Derived Layout Values
  // =============================================

  // Total height of the paper stack including all pages + gaps
  let totalPaperHeight = $derived(
    pageCount * (PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y) + (pageCount - 1) * PAGE_GAP
  );

  // CSS gradient for page/gap pattern: white for pages, transparent for gaps
  let paperBgStyle = $derived.by(() => {
    if (pageCount <= 1) return '';

    const pageHeight = PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y;
    const stops: string[] = [];

    for (let i = 0; i < pageCount; i++) {
      const pageStart = i * (pageHeight + PAGE_GAP);
      const pageEnd = pageStart + pageHeight;

      stops.push(`white ${pageStart}px, white ${pageEnd}px`);
      if (i < pageCount - 1) {
        stops.push(`transparent ${pageEnd}px, transparent ${pageEnd + PAGE_GAP}px`);
      }
    }

    return `background: linear-gradient(to bottom, ${stops.join(', ')});`;
  });

  // The visible (scaled) dimensions for the scroll container wrapper.
  // CSS transform: scale() doesn't affect layout, so we need a wrapper
  // with explicit dimensions matching the visual size.
  let scaledWidth = $derived(Math.ceil(PAGE_WIDTH * (zoomLevel / 100)));
  let scaledHeight = $derived(Math.ceil(totalPaperHeight * (zoomLevel / 100)));

  // =============================================
  // Action Handlers
  // =============================================

  // Copy document content to clipboard (plain text).
  async function handleCopy() {
    try {
      const contentToCopy = localPiiRevealed && hasPII
        ? restorePIIInText(htmlContent, piiMappings)
        : replacePIIOriginalsWithPlaceholders(htmlContent, piiMappings);
      let plainText = stripHtmlTags(contentToCopy);
      plainText = await replaceEmbedRefsWithUrls(plainText);
      const clipResult = await copyToClipboard(plainText);
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      console.debug('[DocsEmbedFullscreen] Copied document text to clipboard');
      notificationStore.success('Document copied to clipboard');
    } catch (error) {
      console.error('[DocsEmbedFullscreen] Failed to copy document:', error);
      notificationStore.error('Failed to copy document to clipboard');
    }
  }

  // Download document as a valid .docx file
  async function handleDownload() {
    try {
      console.debug('[DocsEmbedFullscreen] Starting document download as .docx');

      const { asBlob } = await import('html-docx-js-typescript');
      const downloadFilename = (displayFilename || 'document').replace(/\.docx$/i, '') + '.docx';

      let downloadHtmlContent = localPiiRevealed && hasPII
        ? sanitizeDocumentHtml(restorePIIInText(htmlContent, piiMappings))
        : sanitizeDocumentHtml(replacePIIOriginalsWithPlaceholders(htmlContent, piiMappings));

      downloadHtmlContent = await replaceEmbedRefsWithUrlsInHtml(downloadHtmlContent);

      const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>${displayTitle || 'Document'}</title>
  <style>
    body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #333; }
    h1 { font-size: 20pt; margin-bottom: 0.5em; }
    h2 { font-size: 16pt; margin-top: 1.5em; }
    h3 { font-size: 13pt; margin-top: 1.2em; }
    p { margin: 0.5em 0; }
    ul, ol { padding-left: 2em; }
    blockquote { border-left: 3px solid #ccc; margin: 1em 0; padding: 0.5em 1em; color: #666; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { border: 1px solid #999; padding: 6px 10px; text-align: left; }
    th { background: #f0f0f0; font-weight: bold; }
    code { font-family: 'Courier New', monospace; background: #f5f5f5; padding: 2px 4px; font-size: 10pt; }
    pre { background: #f5f5f5; padding: 12px; font-family: 'Courier New', monospace; font-size: 10pt; white-space: pre-wrap; }
    a { color: #0563C1; }
    img { max-width: 100%; }
  </style>
</head>
<body>
${downloadHtmlContent}
</body>
</html>`;

      const docxBlob = await asBlob(fullHtml, {
        margins: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      }) as Blob;

      const url = URL.createObjectURL(docxBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadFilename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      notificationStore.success('Document downloaded successfully');
    } catch (error) {
      console.error('[DocsEmbedFullscreen] Failed to download document:', error);
      notificationStore.error('Failed to download document');
    }
  }

  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
</script>

<UnifiedEmbedFullscreen
  appId="docs"
  skillId="doc"
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  skillIconName={skillIconName}
  embedHeaderTitle={displayFilename}
  embedHeaderSubtitle={statusText}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  showPIIToggle={hasPII}
  piiRevealed={localPiiRevealed}
  onTogglePII={togglePII}
>
  {#snippet content()}
    {#if sanitizedHtml}
      <div class="doc-viewer-canvas">
        <!--
          Scrollable grey canvas area.
          Contains the scaled paper stack (white pages on grey background).
          The scroll container is the reference for auto-fit zoom calculation.
        -->
        <div class="doc-canvas-scroll" bind:this={canvasScrollEl}>
          <!--
            Scroll-size wrapper: explicit dimensions matching the visual (scaled) size.
            CSS transform: scale() doesn't affect layout flow, so this wrapper
            ensures the scrollable area matches what the user actually sees.
          -->
          <div
            class="doc-scroll-sizer"
            style="width: {scaledWidth}px; min-height: {scaledHeight}px;"
          >
            <div
              class="doc-page-scaler"
              style="transform: scale({zoomLevel / 100}); transform-origin: top center;"
            >
              <!--
                Paper stack: the white page area.
                Background gradient draws white (page) and transparent (gap) bands.
                Absolute-positioned shadow divs sit behind each page for depth.
              -->
              <div
                class="doc-paper-stack"
                style="min-height: {totalPaperHeight}px; {paperBgStyle}"
              >
                <!-- Per-page drop shadows for a realistic floating paper look -->
                {#each Array.from({ length: pageCount }, (__, idx) => idx) as i}
                  <div
                    class="doc-page-shadow"
                    style="top: {i * (PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y + PAGE_GAP)}px; height: {PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y}px;"
                    aria-hidden="true"
                  ></div>
                {/each}

                <!--
                  Content wrapper: inset with A4 page margins.
                  96px top/bottom (1 inch), 72px left/right (0.75 inch — Word default).
                  Content flows naturally; injected spacer divs push text past page-break gaps.
                -->
                <div class="doc-content-wrapper">
                  <div class="doc-page-content" bind:this={contentEl}>
                    <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is sanitized via DOMPurify -->
                    {@html sanitizedHtml}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!--
          Floating zoom controls at the bottom center of the canvas.
          Bright rounded pill with −, %, + buttons.
        -->
        <div class="doc-zoom-bar">
          <div class="doc-zoom-bar-inner">
            <button class="doc-zoom-btn" onclick={zoomOut} aria-label="Zoom out" disabled={zoomIndex === 0}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
            <button class="doc-zoom-level" onclick={resetZoom} aria-label="Reset zoom" title="Click to fit page to screen">
              {zoomLevel}%
            </button>
            <button class="doc-zoom-btn" onclick={zoomIn} aria-label="Zoom in" disabled={zoomIndex === ZOOM_LEVELS.length - 1}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    {:else}
      <div class="empty-state">
        <p>{$text('embeds.document_no_content')}</p>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Document Viewer Canvas
     Full-height flex column that fills the content slot.
     position: relative so the floating zoom bar can be
     positioned absolutely within it.
     The top ~72px is occupied by the absolute-positioned
     action buttons from UnifiedEmbedFullscreen.
     =========================================== */

  .doc-viewer-canvas {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    /* Dark grey canvas — matches Google Docs dark mode canvas */
    background: #3c3c3c;
    /* Push content below the floating top action bar (72px height) */
    padding-top: 72px;
    box-sizing: border-box;
    position: relative;
  }

  /* ===========================================
     Scrollable Canvas Area
     The grey area where pages float.
     Takes all available space in the flex column.
     =========================================== */

  .doc-canvas-scroll {
    flex: 1;
    overflow: auto;
    display: flex;
    justify-content: center;
    /* Padding around the page: top/sides for breathing room,
       extra bottom for the floating zoom bar (56px bar + 16px bottom). */
    padding: 32px 24px 80px;
    box-sizing: border-box;
    scrollbar-width: thin;
    scrollbar-color: rgba(255, 255, 255, 0.15) transparent;
  }

  .doc-canvas-scroll::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  .doc-canvas-scroll::-webkit-scrollbar-track {
    background: transparent;
  }

  .doc-canvas-scroll::-webkit-scrollbar-thumb {
    background-color: rgba(255, 255, 255, 0.15);
    border-radius: 4px;
  }

  .doc-canvas-scroll::-webkit-scrollbar-thumb:hover {
    background-color: rgba(255, 255, 255, 0.28);
  }

  /* ===========================================
     Scroll-Size Wrapper
     Explicit dimensions matching the visual (scaled) size.
     CSS transform: scale() doesn't affect layout, so without
     this wrapper the scroll area wouldn't match visible size.
     =========================================== */

  .doc-scroll-sizer {
    flex-shrink: 0;
    position: relative;
  }

  /* ===========================================
     Page Scaler
     A fixed-width container (A4: 794px at 96 DPI).
     We scale via CSS transform for zoom so layout
     measurements stay stable and text stays sharp.
     =========================================== */

  .doc-page-scaler {
    width: 794px; /* A4 width at 96 DPI */
    flex-shrink: 0;
    transition: transform 0.18s ease;
    transform-origin: top center;
  }

  /* ===========================================
     Paper Stack
     White region representing the document pages.
     Background gradient paints white for pages and
     transparent (revealing dark canvas) for gaps.
     =========================================== */

  .doc-paper-stack {
    width: 100%;
    position: relative;
    background: white;
    border-radius: 2px;
  }

  /* ===========================================
     Per-Page Drop Shadow
     Each page gets its own absolute-positioned
     shadow overlay for a floating paper effect.
     =========================================== */

  .doc-page-shadow {
    position: absolute;
    left: 0;
    right: 0;
    border-radius: 2px;
    pointer-events: none;
    box-shadow:
      0 2px 6px rgba(0, 0, 0, 0.35),
      0 8px 24px rgba(0, 0, 0, 0.25);
    z-index: 0;
  }

  /* ===========================================
     Content Wrapper
     Inset from the paper edges by A4 standard margins:
     96px top/bottom (1 inch), 72px left/right (0.75 inch).
     This is the printable area of each page.
     =========================================== */

  .doc-content-wrapper {
    position: relative;
    /* A4 margins: 1" top/bottom, 0.75" left/right */
    margin: 96px 72px;
    z-index: 1;
  }

  /* ===========================================
     Document Content Typography
     Matches the style of a clean Word/Google Docs document.
     =========================================== */

  .doc-page-content {
    font-family: 'Calibri', 'Cambria', Georgia, 'Times New Roman', serif;
    font-size: 14px;
    font-weight: 400;
    line-height: 1.65;
    color: #202020;
    word-break: break-word;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  .doc-page-content :global(h1) {
    font-size: 24px;
    font-weight: 700;
    margin: 0 0 20px;
    padding-bottom: 10px;
    border-bottom: 2px solid #e8e8e8;
    color: #1a1a1a;
    line-height: 1.25;
    letter-spacing: -0.3px;
  }

  .doc-page-content :global(h2) {
    font-size: 18px;
    font-weight: 600;
    margin: 32px 0 10px;
    color: #1a1a1a;
    line-height: 1.3;
    letter-spacing: -0.2px;
  }

  .doc-page-content :global(h3) {
    font-size: 15px;
    font-weight: 600;
    margin: 24px 0 8px;
    color: #2c2c2c;
    line-height: 1.35;
  }

  .doc-page-content :global(h4),
  .doc-page-content :global(h5),
  .doc-page-content :global(h6) {
    font-size: 14px;
    font-weight: 600;
    margin: 18px 0 6px;
    color: #333;
    line-height: 1.4;
  }

  .doc-page-content :global(p) {
    margin: 0 0 10px;
  }

  .doc-page-content :global(ul),
  .doc-page-content :global(ol) {
    padding-left: 24px;
    margin: 0 0 10px;
  }

  .doc-page-content :global(li) {
    margin: 3px 0;
    line-height: 1.6;
  }

  .doc-page-content :global(li > ul),
  .doc-page-content :global(li > ol) {
    margin: 3px 0;
  }

  .doc-page-content :global(blockquote) {
    border-left: 3px solid #c0c0c0;
    margin: 16px 0 16px 8px;
    padding: 4px 16px;
    color: #555;
    font-style: italic;
  }

  .doc-page-content :global(blockquote p) {
    margin: 4px 0;
  }

  .doc-page-content :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    font-size: 13px;
  }

  .doc-page-content :global(th),
  .doc-page-content :global(td) {
    border: 1px solid #d0d0d0;
    padding: 7px 12px;
    text-align: left;
    vertical-align: top;
  }

  .doc-page-content :global(th) {
    background: #f2f2f2;
    font-weight: 600;
    color: #1a1a1a;
    font-size: 12px;
    text-transform: none;
    letter-spacing: 0;
  }

  .doc-page-content :global(tr:nth-child(even) td) {
    background: #fafafa;
  }

  .doc-page-content :global(code) {
    background: #f5f5f5;
    border: 1px solid #e0e0e0;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 12.5px;
    font-family: 'Consolas', 'SF Mono', 'Fira Mono', 'Courier New', monospace;
    color: #c7254e;
    font-style: normal;
  }

  .doc-page-content :global(pre) {
    background: #f8f8f8;
    padding: 14px 18px;
    border-radius: 4px;
    overflow-x: auto;
    margin: 14px 0;
    border: 1px solid #e4e4e4;
    font-size: 12.5px;
  }

  .doc-page-content :global(pre code) {
    background: none;
    border: none;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
    line-height: 1.55;
    color: #333;
  }

  .doc-page-content :global(a) {
    color: #1155cc;
    text-decoration: underline;
    text-underline-offset: 2px;
    text-decoration-thickness: 1px;
  }

  .doc-page-content :global(a:hover) {
    color: #0b3a8a;
  }

  .doc-page-content :global(hr) {
    border: none;
    border-top: 1px solid #d8d8d8;
    margin: 24px 0;
  }

  .doc-page-content :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 2px;
    margin: 12px 0;
  }

  .doc-page-content :global(strong) {
    font-weight: 700;
    color: #111;
  }

  .doc-page-content :global(em) {
    font-style: italic;
  }

  .doc-page-content :global(dl) {
    margin: 12px 0;
  }

  .doc-page-content :global(dt) {
    font-weight: 600;
    margin-top: 8px;
    color: #1a1a1a;
  }

  .doc-page-content :global(dd) {
    margin-left: 24px;
    margin-bottom: 6px;
    color: #444;
  }

  /* ===========================================
     Floating Zoom Bar
     Positioned at the bottom center of the canvas.
     Bright rounded pill design matching the Figma reference.
     =========================================== */

  .doc-zoom-bar {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10;
    pointer-events: none;
  }

  .doc-zoom-bar-inner {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--color-grey-0, #ffffff);
    border-radius: 28px;
    padding: 4px 6px;
    box-shadow:
      0 2px 8px rgba(0, 0, 0, 0.15),
      0 0 1px rgba(0, 0, 0, 0.1);
    pointer-events: auto;
  }

  /* Zoom +/− round buttons */
  .doc-zoom-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: var(--color-grey-70, #555);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.15s, color 0.15s;
    padding: 0;
    flex-shrink: 0;
  }

  .doc-zoom-btn:hover:not(:disabled) {
    background: var(--color-grey-10, #f0f0f0);
    color: var(--color-grey-100, #1a1a1a);
  }

  .doc-zoom-btn:active:not(:disabled) {
    background: var(--color-grey-20, #e5e5e5);
  }

  .doc-zoom-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  /* Zoom percentage pill — shows current level, resets on click */
  .doc-zoom-level {
    min-width: 52px;
    height: 32px;
    border-radius: 16px;
    border: 1px solid var(--color-grey-20, #e5e5e5);
    background: var(--color-grey-5, #fafafa);
    color: var(--color-grey-80, #333);
    font-size: 13px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 10px;
    transition: background-color 0.15s, border-color 0.15s;
    letter-spacing: 0.2px;
  }

  .doc-zoom-level:hover {
    background: var(--color-grey-10, #f0f0f0);
    border-color: var(--color-grey-30, #ccc);
  }

  /* ===========================================
     Empty State
     =========================================== */

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: rgba(255, 255, 255, 0.5);
  }

  /* ===========================================
     Responsive: Narrow containers
     Uses @container fullscreen queries per project standards.
     The A4 page structure is ALWAYS preserved — only padding
     adjusts for narrow widths. Zoom auto-fits on mount.
     =========================================== */

  @container fullscreen (max-width: 500px) {
    .doc-canvas-scroll {
      padding: 20px 8px 72px;
    }

    .doc-zoom-bar {
      bottom: 12px;
    }
  }
</style>
