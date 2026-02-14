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
    onShowChat
  }: Props = $props();
  
  // Sanitize HTML content for safe rendering (DOMPurify)
  let sanitizedHtml = $derived(sanitizeDocumentHtml(htmlContent));
  
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
  
  // Handle copy document content to clipboard (plain text)
  async function handleCopy() {
    try {
      const plainText = stripHtmlTags(htmlContent);
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
${sanitizedHtml}
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
>
  {#snippet content()}
    {#if sanitizedHtml}
      <div class="doc-viewer-canvas">
        <!-- Zoom controls bar -->
        <div class="doc-zoom-bar">
          <button class="zoom-btn" onclick={zoomOut} aria-label="Zoom out" disabled={zoomIndex === 0}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </button>
          <button class="zoom-label" onclick={resetZoom} aria-label="Reset zoom" title="Click to reset">
            {zoomLevel}%
          </button>
          <button class="zoom-btn" onclick={zoomIn} aria-label="Zoom in" disabled={zoomIndex === ZOOM_LEVELS.length - 1}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </button>
          {#if pageCount > 1}
            <span class="page-count-label">{pageCount} pages</span>
          {/if}
        </div>

        <!-- Scrollable area with grey canvas -->
        <div class="doc-page-scroll">
          <div class="doc-page-scaler" style="transform: scale({zoomLevel / 100}); transform-origin: top center;">
            <!--
              Paper stack container:
              - Sized to hold all pages (1056px each) with 32px gaps between them
              - Background gradient paints white page rects and transparent (grey) gaps
              - Individual box-shadow overlays give each page its drop shadow
            -->
            <div
              class="doc-paper-stack"
              style="height: {totalPaperHeight}px; {paperBgStyle}"
            >
              <!-- Per-page drop shadows for realistic paper look -->
              {#each Array(pageCount) as _, i}
                <div
                  class="doc-page-shadow"
                  style="top: {i * (PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y + PAGE_GAP)}px; height: {PAGE_CONTENT_HEIGHT + 2 * PAGE_MARGIN_Y}px;"
                ></div>
              {/each}

              <!--
                Content wrapper: starts at the first page top margin (96px from top).
                Has left/right margins matching page margins.
                Content flows naturally through the wrapper.
                Injected spacer divs at page breaks push content past the grey gaps.
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
     =========================================== */
  
  .doc-viewer-canvas {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--color-grey-15);
    /* No extra padding-top: the zoom bar and action buttons handle their own spacing.
       The top-bar from UnifiedEmbedFullscreen is absolutely positioned. */
  }
  
  /* ===========================================
     Zoom Controls
     =========================================== */
  
  .doc-zoom-bar {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 8px 0;
    flex-shrink: 0;
    z-index: 5;
  }
  
  .zoom-btn {
    width: 32px;
    height: 32px;
    border-radius: 6px;
    border: none;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.15s, color 0.15s;
    padding: 0;
    min-width: auto;
  }
  
  .zoom-btn:hover:not(:disabled) {
    background: var(--color-grey-30);
    color: var(--color-font-primary);
  }
  
  .zoom-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }
  
  .zoom-label {
    min-width: 52px;
    height: 32px;
    border-radius: 6px;
    border: none;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.15s;
    padding: 0 8px;
  }
  
  .zoom-label:hover {
    background: var(--color-grey-30);
  }

  .page-count-label {
    font-size: 12px;
    color: var(--color-font-secondary);
    margin-left: 8px;
    opacity: 0.7;
  }
  
  /* ===========================================
     Scrollable Area
     =========================================== */
  
  .doc-page-scroll {
    flex: 1;
    overflow: auto;
    display: flex;
    justify-content: center;
    /* Side padding for the paper, bottom space for the floating BasicInfosBar */
    padding: 0 24px 80px;
  }

  .doc-page-scaler {
    width: 816px;
    flex-shrink: 0;
    transition: transform 0.2s ease;
  }
  
  /* ===========================================
     Paper Stack
     Holds all pages. Background gradient draws
     the white/grey pattern. Grey = canvas showing.
     =========================================== */
  
  .doc-paper-stack {
    width: 100%;
    position: relative;
    background: white; /* fallback for single page */
    border-radius: 4px;
  }

  /* ===========================================
     Per-Page Drop Shadow
     =========================================== */

  .doc-page-shadow {
    position: absolute;
    left: 0;
    right: 0;
    border-radius: 4px;
    pointer-events: none;
    box-shadow: 
      0 1px 3px rgba(0, 0, 0, 0.12),
      0 4px 12px rgba(0, 0, 0, 0.08);
    z-index: 0;
  }

  /* ===========================================
     Content Wrapper
     Positioned inside the paper stack, offset by
     the first page's top margin. Left/right margins
     match page margins. Content flows through,
     with spacer divs injected at page breaks.
     =========================================== */

  .doc-content-wrapper {
    position: relative;
    margin: 96px 96px 96px; /* Page margins: top, left/right, bottom */
    z-index: 1;
  }

  /* ===========================================
     Document Content Typography
     =========================================== */
  
  .doc-page-content {
    color: #1a1a1a;
    font-size: 15px;
    line-height: 1.75;
    word-break: break-word;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  }

  .doc-page-content :global(h1) {
    font-size: 26px;
    font-weight: 700;
    margin: 0 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e0e0e0;
    color: #0d0d0d;
    line-height: 1.3;
  }

  .doc-page-content :global(h2) {
    font-size: 21px;
    font-weight: 600;
    margin: 28px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid #eeeeee;
    color: #1a1a1a;
    line-height: 1.35;
  }

  .doc-page-content :global(h3) {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 8px;
    color: #1a1a1a;
    line-height: 1.4;
  }

  .doc-page-content :global(h4),
  .doc-page-content :global(h5),
  .doc-page-content :global(h6) {
    font-size: 16px;
    font-weight: 600;
    margin: 20px 0 6px;
    color: #2a2a2a;
    line-height: 1.4;
  }

  .doc-page-content :global(p) {
    margin: 0 0 12px;
  }

  .doc-page-content :global(ul),
  .doc-page-content :global(ol) {
    padding-left: 28px;
    margin: 0 0 12px;
  }

  .doc-page-content :global(li) {
    margin: 4px 0;
  }

  .doc-page-content :global(li > ul),
  .doc-page-content :global(li > ol) {
    margin: 4px 0;
  }

  .doc-page-content :global(blockquote) {
    border-left: 3px solid #1a73e8;
    margin: 16px 0;
    padding: 8px 16px;
    color: #555;
    background: #f8f9fa;
    border-radius: 0 4px 4px 0;
  }

  .doc-page-content :global(blockquote p) {
    margin: 4px 0;
  }

  .doc-page-content :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    font-size: 14px;
  }

  .doc-page-content :global(th),
  .doc-page-content :global(td) {
    border: 1px solid #dadce0;
    padding: 10px 14px;
    text-align: left;
  }

  .doc-page-content :global(th) {
    background: #f1f3f4;
    font-weight: 600;
    color: #1a1a1a;
  }

  .doc-page-content :global(tr:nth-child(even)) {
    background: #fafafa;
  }

  .doc-page-content :global(code) {
    background: #f1f3f4;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    color: #d63384;
  }

  .doc-page-content :global(pre) {
    background: #f8f9fa;
    padding: 16px 20px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
    border: 1px solid #e8eaed;
  }

  .doc-page-content :global(pre code) {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 13px;
    line-height: 1.5;
    color: inherit;
  }

  .doc-page-content :global(a) {
    color: #1a73e8;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .doc-page-content :global(a:hover) {
    color: #1558b0;
  }

  .doc-page-content :global(hr) {
    border: none;
    border-top: 1px solid #dadce0;
    margin: 28px 0;
  }

  .doc-page-content :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
    margin: 12px 0;
  }

  .doc-page-content :global(strong) {
    font-weight: 600;
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
  }

  .doc-page-content :global(dd) {
    margin-left: 28px;
    margin-bottom: 8px;
  }

  /* ===========================================
     Empty State
     =========================================== */
  
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }

  /* ===========================================
     Responsive: Mobile
     =========================================== */
  
  @media (max-width: 900px) {
    .doc-page-scaler {
      width: 100%;
    }
    
    .doc-paper-stack {
      border-radius: 0;
      height: auto !important;
      background: white !important;
    }

    .doc-content-wrapper {
      margin: 40px 32px 60px;
    }

    .doc-page-shadow {
      display: none;
    }
    
    .doc-page-scroll {
      padding: 0 0 80px;
    }
    
    .doc-page-content {
      font-size: 14px;
    }
    
    .doc-page-content :global(h1) {
      font-size: 22px;
    }
    
    .doc-page-content :global(h2) {
      font-size: 18px;
    }
    
    .doc-page-content :global(h3) {
      font-size: 16px;
    }
  }
</style>
