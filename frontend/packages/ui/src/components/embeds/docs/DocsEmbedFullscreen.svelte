<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedFullscreen.svelte
  
  Fullscreen view for Document embeds (document_html).
  Uses UnifiedEmbedFullscreen as base and provides document-specific content.
  
  Designed to look like reading a document in Microsoft Word / Google Docs:
  - Grey background canvas (the grey area around and between pages)
  - White A4-ratio pages centered with shadow (like printed pages)
  - Content flows naturally; grey gaps appear between pages
  - Zoom controls to scale the document view
  - Filename shown in bottom bar (e.g., "Report.docx")
  - Copy (plain text), Download (as .docx), Share actions
  
  Page rendering approach:
  1. Render all content in a single tall white div with page margins
  2. Measure the content, calculate how many pages are needed
  3. The paper-stack container uses a CSS gradient background that draws
     grey gaps at each page boundary
  4. A column layout on the content wrapper creates "column breaks" at
     page boundaries by using CSS column-fill with a fixed column height
     equal to the page content height. Each column = one page of content.
     The columns are stacked vertically (not side by side) via a transform.
     
  Actually, the simplest correct approach:
  We use a single white container with content flowing normally.
  At each page boundary, the grey gap is painted as a background band
  that overlays the white. The content text does flow through these bands,
  but we offset it using a CSS trick: the content wrapper uses
  `background-clip: content-box` with vertical padding that accounts for 
  the grey gaps.
  
  Final approach (what we actually do):
  We render content once. After measuring, we insert invisible "spacer"
  elements into the DOM at page-break Y positions. Each spacer has a
  height equal to the gap + top/bottom page margins. This pushes subsequent
  content past the grey gap area. The background gradient draws the
  page/gap pattern, and the spacers keep text aligned to page content areas.
-->

<script lang="ts">
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
    showChatButton = false,
    onShowChat,
    piiMappings = [],
    piiRevealed = false
  }: Props = $props();

  // Local PII reveal toggle — initialised from prop but user can flip it in fullscreen.
  // We use a local state so the fullscreen can show/hide independently without
  // requiring a prop change from the parent (the parent toggle already covers the chat view).
  let localPiiRevealed = $state(piiRevealed);

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
   * The AI may include placeholder strings (e.g. "[EMAIL_1]") in document content.
   * When localPiiRevealed is true, we restore originals so the user can read the full content.
   * When false, placeholders remain as-is (privacy mode).
   */
  let piiProcessedHtml = $derived.by(() => {
    if (!hasPII || !htmlContent) return htmlContent;
    if (localPiiRevealed) {
      // Show originals: replace placeholders with original values
      return restorePIIInText(htmlContent, piiMappings);
    } else {
      // Hide originals: ensure originals are replaced back with placeholders
      // (needed in case the content was already restored elsewhere)
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
  
  // Build skill name for BasicInfosBar: show filename (e.g., "Report.docx")
  let skillName = $derived(displayFilename);
  
  // No header in fullscreen for documents (buttons overlay the top area)
  const fullscreenTitle = '';
  
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
  // US Letter Page Dimensions (at 96 DPI)
  // =============================================
  // US Letter: 8.5" × 11" = 816 × 1056 px
  // Page margin: 96px top/bottom (1 inch), 96px left/right
  // Usable content height per page: 1056 - 96 - 96 = 864px
  // Gap between pages: 32px (grey canvas visible)
  // At each page break, the spacer height = bottom margin + gap + top margin = 96 + 32 + 96 = 224px
  const PAGE_CONTENT_HEIGHT = 864;
  const PAGE_GAP = 32;
  const PAGE_MARGIN_Y = 96;
  const SPACER_HEIGHT = PAGE_MARGIN_Y + PAGE_GAP + PAGE_MARGIN_Y; // 224px

  // Zoom state
  const ZOOM_LEVELS = [50, 75, 100, 125, 150, 200];
  let zoomIndex = $state(2); // Start at 100%
  let zoomLevel = $derived(ZOOM_LEVELS[zoomIndex]);
  
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
  
  function resetZoom() {
    zoomIndex = 2; // 100%
  }

  // =============================================
  // Page Break Spacer Injection
  // =============================================
  // After content renders, we walk the DOM to find which elements
  // cross page boundaries, and insert spacer divs that push
  // subsequent content into the next page's content area.
  //
  // This is the same technique used by Google Docs:
  // content flows naturally, but spacers at page breaks
  // ensure text doesn't appear in the grey gap between pages.
  let contentEl: HTMLDivElement | undefined = $state(undefined);
  let pageCount = $state(1);

  // CSS class for injected spacers so we can identify and remove them
  const SPACER_CLASS = 'doc-page-break-spacer';

  $effect(() => {
    if (!contentEl || !sanitizedHtml) {
      pageCount = 1;
      return;
    }

    const raf = requestAnimationFrame(() => {
      if (!contentEl) return;
      
      // Remove any previously injected spacers
      contentEl.querySelectorAll(`.${SPACER_CLASS}`).forEach(el => el.remove());

      // Measure the natural content height (without spacers)
      const naturalHeight = contentEl.scrollHeight;
      const numPages = Math.max(1, Math.ceil(naturalHeight / PAGE_CONTENT_HEIGHT));
      
      if (numPages <= 1) {
        pageCount = numPages;
        return;
      }

      // For each page break (between page N and page N+1), find the child element
      // that straddles the boundary and insert a spacer before it.
      // We work from bottom to top so insertions don't shift positions of earlier breaks.
      let insertedSpacers = 0;
      
      for (let breakIdx = numPages - 1; breakIdx >= 1; breakIdx--) {
        // The Y position of this page break in the content (before any spacers from this pass)
        // Account for spacers already inserted below this point
        const breakY = breakIdx * PAGE_CONTENT_HEIGHT + insertedSpacers * SPACER_HEIGHT;
        
        // Find the top-level child element that contains or straddles this break point
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
          
          // Insert spacer before the element that crosses the page boundary
          contentEl.insertBefore(spacer, targetChild);
          insertedSpacers++;
        }
      }
      
      pageCount = numPages;
    });

    return () => cancelAnimationFrame(raf);
  });

  // Total height of the paper stack including all pages + gaps
  let totalPaperHeight = $derived(
    pageCount * (PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y) + (pageCount - 1) * PAGE_GAP
  );

  // Build CSS gradient that paints the page background pattern:
  // white for each page area, transparent (grey shows through) for gaps
  let paperBgStyle = $derived.by(() => {
    if (pageCount <= 1) return '';
    
    const pageHeight = PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y; // 1056
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
  
  // Handle copy document content to clipboard (plain text).
  // When PII is revealed, copy the restored (original) text.
  // When PII is hidden, copy placeholder strings so sensitive data is not leaked.
  async function handleCopy() {
    try {
      const contentToCopy = localPiiRevealed && hasPII
        ? restorePIIInText(htmlContent, piiMappings)
        : replacePIIOriginalsWithPlaceholders(htmlContent, piiMappings);
      const plainText = stripHtmlTags(contentToCopy);
      await navigator.clipboard.writeText(plainText);
      console.debug('[DocsEmbedFullscreen] Copied document text to clipboard');
      notificationStore.success('Document copied to clipboard');
    } catch (error) {
      console.error('[DocsEmbedFullscreen] Failed to copy document:', error);
      notificationStore.error('Failed to copy document to clipboard');
    }
  }

  // Handle download document as a valid .docx file
  async function handleDownload() {
    try {
      console.debug('[DocsEmbedFullscreen] Starting document download as .docx');

      const { asBlob } = await import('html-docx-js-typescript');
      const downloadFilename = (displayFilename || 'document').replace(/\.docx$/i, '') + '.docx';

      // Use the PII-processed and sanitized content for download, respecting reveal state.
      const downloadHtmlContent = localPiiRevealed && hasPII
        ? sanitizeDocumentHtml(restorePIIInText(htmlContent, piiMappings))
        : sanitizeDocumentHtml(replacePIIOriginalsWithPlaceholders(htmlContent, piiMappings));

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
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
</script>

<UnifiedEmbedFullscreen
  appId="docs"
  skillId="doc"
  title={fullscreenTitle}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  skillIconName={skillIconName}
  status="finished"
  {skillName}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
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
          Google Docs-style toolbar: sits below the top action buttons (which are absolute positioned
          at top: 16px by UnifiedEmbedFullscreen and take ~72px of space).
          The toolbar has a subtle separator and contains zoom controls + page count.
        -->
        <div class="doc-toolbar">
          <div class="doc-toolbar-inner">
            <button class="zoom-btn" onclick={zoomOut} aria-label="Zoom out" disabled={zoomIndex === 0}>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
            <button class="zoom-pill" onclick={resetZoom} aria-label="Reset zoom to 100%" title="Click to reset zoom">
              {zoomLevel}%
            </button>
            <button class="zoom-btn" onclick={zoomIn} aria-label="Zoom in" disabled={zoomIndex === ZOOM_LEVELS.length - 1}>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
            {#if pageCount > 1}
              <span class="toolbar-separator" aria-hidden="true"></span>
              <span class="page-count-label">{pageCount} {pageCount === 1 ? 'page' : 'pages'}</span>
            {/if}
          </div>
        </div>

        <!--
          Scrollable grey canvas area.
          Contains the scaled paper stack (white pages on grey background).
        -->
        <div class="doc-canvas-scroll">
          <div
            class="doc-page-scaler"
            style="--zoom: {zoomLevel / 100}; transform: scale(var(--zoom)); transform-origin: top center;"
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
                Content wrapper: inset with page margins (top/bottom/left/right = 96px = ~1 inch at 96dpi).
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
     The top ~72px is occupied by the absolute-positioned
     action buttons from UnifiedEmbedFullscreen, so we
     add padding-top to avoid overlap.
     =========================================== */

  .doc-viewer-canvas {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    /* Charcoal/dark grey canvas — matches Google Docs dark mode canvas */
    background: #3c3c3c;
    /* Push content below the floating top action bar (72px height) */
    padding-top: 72px;
    box-sizing: border-box;
  }

  /* ===========================================
     Google Docs-style Toolbar
     A thin strip sitting just above the document canvas.
     Contains zoom controls and page count.
     Dark background with subtle bottom border to separate from canvas.
     =========================================== */

  .doc-toolbar {
    flex-shrink: 0;
    background: #2e2e2e;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 6px 16px;
    height: 42px;
    box-sizing: border-box;
  }

  .doc-toolbar-inner {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  /* Zoom ± buttons */
  .zoom-btn {
    width: 28px;
    height: 28px;
    border-radius: 4px;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.1s, color 0.1s;
    padding: 0;
    flex-shrink: 0;
  }

  .zoom-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.12);
    color: #fff;
  }

  .zoom-btn:disabled {
    opacity: 0.25;
    cursor: not-allowed;
  }

  /* Zoom level pill — shows current % and resets on click */
  .zoom-pill {
    min-width: 54px;
    height: 28px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 8px;
    transition: background-color 0.1s, border-color 0.1s;
    margin: 0 2px;
    letter-spacing: 0.3px;
  }

  .zoom-pill:hover {
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(255, 255, 255, 0.3);
    color: #fff;
  }

  /* Thin vertical separator between zoom and page count */
  .toolbar-separator {
    width: 1px;
    height: 16px;
    background: rgba(255, 255, 255, 0.15);
    margin: 0 10px;
    flex-shrink: 0;
  }

  .page-count-label {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.5);
    white-space: nowrap;
    letter-spacing: 0.2px;
  }

  /* ===========================================
     Scrollable Canvas Area
     The grey area where pages float.
     =========================================== */

  .doc-canvas-scroll {
    flex: 1;
    overflow: auto;
    display: flex;
    justify-content: center;
    /* Generous top/bottom padding so pages don't hug edges.
       Extra bottom padding for the floating BasicInfosBar. */
    padding: 32px 40px 100px;
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
     Page Scaler
     A fixed-width container (US Letter: 816px).
     We scale via CSS transform for zoom so layout
     measurements stay stable and text stays sharp.
     =========================================== */

  .doc-page-scaler {
    /* US Letter at 96 dpi = 816px wide */
    width: 816px;
    flex-shrink: 0;
    transition: transform 0.18s ease;
    /* Scale from the top-center so the page stays anchored at the top */
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
    /* White fallback for single-page documents */
    background: white;
    /* Outer border-radius makes the edges of the paper block slightly rounded */
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
    /* Two-layer shadow: close soft shadow + distant diffuse shadow */
    box-shadow:
      0 2px 6px rgba(0, 0, 0, 0.35),
      0 8px 24px rgba(0, 0, 0, 0.25);
    z-index: 0;
  }

  /* ===========================================
     Content Wrapper
     Inset from the paper edges by 1 inch (96px at 96dpi).
     This is the printable area of each page.
     =========================================== */

  .doc-content-wrapper {
    position: relative;
    /* 1-inch margins on all sides (96px at 96 DPI) */
    margin: 96px;
    z-index: 1;
  }

  /* ===========================================
     Document Content Typography
     Matches the style of a clean Word/Google Docs document:
     - Light-weight body text (not bold)
     - Calibri/Georgia-like reading experience
     - Generous line height
     - Black text on white, proper heading hierarchy
     =========================================== */

  .doc-page-content {
    /* Document body font: prioritise Calibri (Word), then Georgia/serif for elegance */
    font-family: 'Calibri', 'Cambria', Georgia, 'Times New Roman', serif;
    font-size: 14px;       /* ~11pt — standard Word document body size */
    font-weight: 400;      /* Normal weight — NOT bold */
    line-height: 1.65;     /* Comfortable reading line height */
    color: #202020;        /* Near-black, slightly softer than pure black */
    word-break: break-word;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* Document H1: Title style */
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

  /* Document H2: Section heading */
  .doc-page-content :global(h2) {
    font-size: 18px;
    font-weight: 600;
    margin: 32px 0 10px;
    color: #1a1a1a;
    line-height: 1.3;
    letter-spacing: -0.2px;
  }

  /* Document H3: Sub-section heading */
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

  /* Paragraph: tight spacing between paragraphs */
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

  /* Blockquote: left-rule style, indented */
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

  /* Tables: professional document table style */
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

  /* Inline code: monospaced, subtle background */
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

  /* Code blocks */
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

  /* Horizontal rule: thin line */
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
     Responsive: Mobile (≤ 900px)
     On narrow screens, drop the fixed page width and
     render a simple single-column white document.
     =========================================== */

  @media (max-width: 900px) {
    .doc-viewer-canvas {
      /* Less top padding on mobile since buttons are smaller */
      padding-top: 72px;
    }

    .doc-canvas-scroll {
      padding: 16px 0 100px;
    }

    .doc-page-scaler {
      width: 100%;
    }

    .doc-paper-stack {
      border-radius: 0;
      /* Override gradient bg on mobile — single flat white page */
      background: white !important;
      min-height: 0 !important;
    }

    .doc-page-shadow {
      display: none;
    }

    .doc-content-wrapper {
      margin: 40px 28px 60px;
    }

    .doc-page-content {
      font-size: 13px;
    }

    .doc-page-content :global(h1) {
      font-size: 20px;
    }

    .doc-page-content :global(h2) {
      font-size: 16px;
    }

    .doc-page-content :global(h3) {
      font-size: 14px;
    }
  }
</style>
