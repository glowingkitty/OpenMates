<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedFullscreen.svelte
  
  Fullscreen view for Document embeds (document_html).
  Uses UnifiedEmbedFullscreen as base and provides document-specific content.
  
  Designed to look like reading a document in Microsoft Word / Google Docs:
  - Grey background canvas (like the grey area around the page)
  - White A4-ratio page centered with shadow (like a printed page)
  - Proper document typography with serif/sans-serif fonts
  - Zoom controls to scale the document view
  - Filename shown in bottom bar (e.g., "Report.docx")
  - Copy (plain text), Download (as .html), Share actions
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
    return extractDocumentTitle(htmlContent) || $text('embeds.document_snippet.text');
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
      ? $text('embeds.document_word_singular.text')
      : $text('embeds.document_word_plural.text');
    
    return `${wc} ${wordText}`;
  });
  
  // Icon for documents
  const skillIconName = 'docs';
  
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

  // Handle download document as a valid .docx file using client-side HTML-to-DOCX conversion.
  // This keeps the content on the client (important for E2E encryption) and avoids server round-trips.
  async function handleDownload() {
    try {
      console.debug('[DocsEmbedFullscreen] Starting document download as .docx');

      // Dynamic import to avoid loading the library until the user actually clicks download
      const { default: HTMLtoDOCX } = await import('html-to-docx');

      const downloadFilename = (displayFilename || 'document').replace(/\.docx$/i, '') + '.docx';

      // Convert sanitized HTML to a valid .docx Blob.
      // html-to-docx expects a clean HTML string for the body content.
      const docxBlob = await HTMLtoDOCX(sanitizedHtml, null, {
        title: displayTitle || 'Document',
        margins: {
          top: 1440,    // 1 inch in TWIP
          right: 1440,
          bottom: 1440,
          left: 1440,
        },
        font: 'Calibri',
        fontSize: 22,   // 11pt in HIP (half-points)
        table: { row: { cantSplit: true } },
      });

      // Create download link and trigger the download
      const blob = docxBlob instanceof Blob ? docxBlob : new Blob([docxBlob]);
      const url = URL.createObjectURL(blob);
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

  // Handle share - opens share settings menu for this specific document embed
  async function handleShare() {
    try {
      console.debug('[DocsEmbedFullscreen] Opening share settings for document embed:', {
        embedId,
        title: displayTitle,
        wordCount: actualWordCount
      });

      if (!embedId) {
        console.warn('[DocsEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        notificationStore.error('Unable to share this document. Missing embed ID.');
        return;
      }

      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      const embedContext = {
        type: 'document',
        embed_id: embedId,
        title: displayTitle,
        wordCount: actualWordCount
      };

      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

      navigateToSettings(
        'shared/share',
        $text('settings.share.share_document.text', { default: 'Share Document' }),
        'share',
        'settings.share.share_document.text'
      );

      settingsDeepLink.set('shared/share');
      panelState.openSettings();

      console.debug('[DocsEmbedFullscreen] Opened share settings for document embed');
    } catch (error) {
      console.error('[DocsEmbedFullscreen] Error opening share settings:', error);
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

<!-- 
  Pass BasicInfosBar props to UnifiedEmbedFullscreen for consistent bottom bar
  Document embeds show: filename + word count
-->
<UnifiedEmbedFullscreen
  appId="docs"
  skillId="doc"
  title={fullscreenTitle}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  onShare={handleShare}
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
      <!-- Google Docs / Word-like document viewer -->
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
        </div>
        
        <!-- Scrollable page area -->
        <div class="doc-page-scroll">
          <div class="doc-page-container" style="transform: scale({zoomLevel / 100}); transform-origin: top center;">
            <!-- White A4 page -->
            <div class="doc-page">
              <div class="doc-page-content">
                <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is sanitized via DOMPurify -->
                {@html sanitizedHtml}
              </div>
            </div>
          </div>
        </div>
      </div>
    {:else}
      <!-- Empty state -->
      <div class="empty-state">
        <p>{$text('embeds.document_no_content.text')}</p>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Document Viewer Canvas - Google Docs style
     Grey background with centered white page
     =========================================== */
  
  .doc-viewer-canvas {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--color-grey-15);
    padding-top: 60px; /* Space for the top action bar */
  }
  
  /* ===========================================
     Zoom Controls Bar
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
  
  /* ===========================================
     Scrollable Page Area
     =========================================== */
  
  .doc-page-scroll {
    flex: 1;
    overflow: auto;
    display: flex;
    justify-content: center;
    padding: 0 24px 100px;
  }
  
  .doc-page-container {
    width: 816px; /* Standard US Letter / A4-ish width at 96 DPI */
    flex-shrink: 0;
    transition: transform 0.2s ease;
  }
  
  /* ===========================================
     White A4 Page
     =========================================== */
  
  .doc-page {
    width: 100%;
    background: white;
    box-shadow: 
      0 1px 3px rgba(0, 0, 0, 0.12),
      0 4px 12px rgba(0, 0, 0, 0.08);
    border-radius: 4px;
    min-height: 1056px; /* A4-ish height at 96 DPI */
    /* Realistic A4 margins: ~1 inch = 96px top/bottom, ~1 inch = 96px left/right */
    padding: 72px 84px 96px;
  }
  
  /* ===========================================
     Document Content Typography
     Clean, professional document styling
     =========================================== */
  
  .doc-page-content {
    color: #1a1a1a;
    font-size: 15px;
    line-height: 1.75;
    word-break: break-word;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  }

  /* Headings */
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

  /* Paragraphs */
  .doc-page-content :global(p) {
    margin: 0 0 12px;
  }

  /* Lists */
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

  /* Blockquotes */
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

  /* Tables */
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

  /* Inline code */
  .doc-page-content :global(code) {
    background: #f1f3f4;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    color: #d63384;
  }

  /* Code blocks */
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

  /* Links */
  .doc-page-content :global(a) {
    color: #1a73e8;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .doc-page-content :global(a:hover) {
    color: #1558b0;
  }

  /* Horizontal rules */
  .doc-page-content :global(hr) {
    border: none;
    border-top: 1px solid #dadce0;
    margin: 28px 0;
  }

  /* Images */
  .doc-page-content :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
    margin: 12px 0;
  }

  /* Strong and emphasis */
  .doc-page-content :global(strong) {
    font-weight: 600;
  }

  .doc-page-content :global(em) {
    font-style: italic;
  }

  /* Definition lists */
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
    padding-top: 80px;
  }

  /* ===========================================
     Responsive: Mobile
     =========================================== */
  
  @media (max-width: 900px) {
    .doc-page-container {
      width: 100%;
    }
    
    .doc-page {
      padding: 40px 32px 60px;
      min-height: auto;
      border-radius: 0;
    }
    
    .doc-page-scroll {
      padding: 0 0 100px;
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
