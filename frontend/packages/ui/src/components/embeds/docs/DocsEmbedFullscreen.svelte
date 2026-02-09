<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedFullscreen.svelte
  
  Fullscreen view for Document embeds (document_html).
  Uses UnifiedEmbedFullscreen as base and provides document-specific content.
  
  Renders documents using CKEditor 5 (DecoupledEditor in read-only mode) for
  accurate HTML rendering that closely matches real document formatting.

  Layout designed to look like reading a document in Microsoft Word / Google Docs:
  - Grey background canvas (the grey area around pages)
  - White document area centered with shadow (like a printed page)
  - Zoom controls to scale the document view
  - Filename shown in bottom bar (e.g., "Report.docx")
  - Copy (plain text), Download (as .docx), Share actions
  
  CKEditor is loaded lazily on first mount to keep initial bundle small.
  Future: Enable editing mode by toggling CKEditor's read-only lock.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import CKEditorDocViewer from './CKEditorDocViewer.svelte';
  import { text } from '@repo/ui';

  /** Minimal type for the CKEditor instance exposed by CKEditorDocViewer */
  interface CKEditorInstance {
    getData: () => string;
    setData: (data: string) => void;
    enableReadOnlyMode: (lockId: string) => void;
    disableReadOnlyMode: (lockId: string) => void;
  }
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
  
  // =============================================
  // Zoom State
  // =============================================
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
  // CKEditor Instance Reference
  // =============================================
  let editorInstance: CKEditorInstance | null = $state(null);

  function handleEditorReady(editor: CKEditorInstance) {
    editorInstance = editor;
    console.debug('[DocsEmbedFullscreen] CKEditor ready');
  }

  // =============================================
  // Actions: Copy, Download, Share
  // =============================================
  
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

      // Use CKEditor's data if available (more accurate), fall back to sanitized HTML
      const contentHtml = editorInstance ? editorInstance.getData() : sanitizedHtml;

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
${contentHtml}
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

  // Handle share
  async function handleShare() {
    try {
      console.debug('[DocsEmbedFullscreen] Opening share settings for document embed:', {
        embedId,
        title: displayTitle,
        wordCount: actualWordCount
      });

      if (!embedId) {
        console.warn('[DocsEmbedFullscreen] No embed_id available');
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
    } catch (error) {
      console.error('[DocsEmbedFullscreen] Error opening share settings:', error);
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

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

        <!-- Scrollable area with grey canvas -->
        <div class="doc-page-scroll">
          <div class="doc-page-scaler" style="transform: scale({zoomLevel / 100}); transform-origin: top center;">
            <!-- White document paper with shadow -->
            <div class="doc-paper">
              <!-- Document content rendered by CKEditor -->
              <div class="doc-content-wrapper">
                <CKEditorDocViewer
                  htmlContent={sanitizedHtml}
                  onReady={handleEditorReady}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    {:else}
      <div class="doc-empty-state">
        <p>{$text('embeds.document_no_content.text')}</p>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Document Viewer Canvas
     Grey background that fills the entire embed
     container from top to bottom.
     =========================================== */
  
  .doc-viewer-canvas {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--color-grey-15);
    /* No extra padding - zoom bar sits at top, content fills to bottom */
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
  
  /* ===========================================
     Scrollable Area
     Fills the remaining space below the zoom bar,
     all the way to the bottom of the container.
     =========================================== */
  
  .doc-page-scroll {
    flex: 1;
    overflow: auto;
    display: flex;
    justify-content: center;
    /* Minimal padding: side padding and bottom space for the
       BasicInfosBar floating overlay from UnifiedEmbedFullscreen */
    padding: 0 24px 80px;
  }

  .doc-page-scaler {
    width: 816px;
    flex-shrink: 0;
    transition: transform 0.2s ease;
  }
  
  /* ===========================================
     Document Paper
     White paper with drop shadow, like a real page.
     Single continuous page - CKEditor handles
     the content rendering.
     =========================================== */
  
  .doc-paper {
    width: 100%;
    background: white;
    border-radius: 4px;
    box-shadow: 
      0 1px 3px rgba(0, 0, 0, 0.12),
      0 4px 12px rgba(0, 0, 0, 0.08);
    min-height: 400px;
  }

  /* ===========================================
     Content Wrapper
     Provides page-like margins around the CKEditor
     content area, matching standard document margins.
     =========================================== */

  .doc-content-wrapper {
    padding: 96px; /* 1 inch margins at 96 DPI */
  }

  /* ===========================================
     Empty State
     =========================================== */
  
  .doc-empty-state {
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
    
    .doc-paper {
      border-radius: 0;
      box-shadow: none;
    }

    .doc-content-wrapper {
      padding: 40px 32px 60px;
    }
    
    .doc-page-scroll {
      padding: 0 0 80px;
    }
  }
</style>
