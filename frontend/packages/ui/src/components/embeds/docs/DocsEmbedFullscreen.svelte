<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedFullscreen.svelte
  
  Fullscreen view for Document embeds (document_html).
  Uses UnifiedEmbedFullscreen as base and provides document-specific content.
  
  Shows:
  - Document title and word count in bottom bar
  - Full sanitized HTML content rendered with proper typography
  - Copy button (copies plain text), Download (as .html file), Share
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import {
    sanitizeDocumentHtml,
    stripHtmlTags,
    countDocWords,
    extractDocumentTitle
  } from './docsEmbedContent';
  
  /**
   * Props for document embed fullscreen
   */
  interface Props {
    /** Document HTML content */
    htmlContent: string;
    /** Document title */
    title?: string;
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
  
  // Calculate word count from content if not provided
  let actualWordCount = $derived.by(() => {
    if (wordCount > 0) return wordCount;
    return countDocWords(htmlContent);
  });
  
  // Build skill name for BasicInfosBar
  let skillName = $derived(displayTitle);
  
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

  // Handle download document as HTML file
  async function handleDownload() {
    try {
      console.debug('[DocsEmbedFullscreen] Starting document download');
      
      // Create a full HTML document with basic styling for readability
      const filename = (displayTitle || 'document').replace(/[^a-zA-Z0-9_-]/g, '_') + '.html';
      const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${displayTitle || 'Document'}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 40px 20px; line-height: 1.6; color: #333; }
    h1 { font-size: 2em; margin-bottom: 0.5em; }
    h2 { font-size: 1.5em; margin-top: 1.5em; }
    h3 { font-size: 1.25em; margin-top: 1.2em; }
    p { margin: 0.8em 0; }
    ul, ol { padding-left: 2em; }
    blockquote { border-left: 3px solid #ccc; margin: 1em 0; padding: 0.5em 1em; color: #666; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
    th { background: #f5f5f5; font-weight: 600; }
    code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
    pre { background: #f5f5f5; padding: 16px; border-radius: 6px; overflow-x: auto; }
    pre code { background: none; padding: 0; }
    a { color: #0066cc; }
    img { max-width: 100%; height: auto; }
  </style>
</head>
<body>
${sanitizedHtml}
</body>
</html>`;
      
      // Create download blob
      const blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
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
  Document embeds show: title + word count
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
      <!-- Full document content with sanitized HTML -->
      <div class="doc-fullscreen-container">
        <div class="doc-fullscreen-content">
          {@html sanitizedHtml}
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
  /* Document fullscreen container */
  .doc-fullscreen-container {
    width: 100%;
    max-width: 800px;
    margin: 70px auto 0;
    padding: 0 24px 40px;
  }

  /* Document content typography - clean document-like rendering */
  .doc-fullscreen-content {
    color: var(--color-font-primary);
    font-size: 16px;
    line-height: 1.7;
    word-break: break-word;
  }

  /* Headings */
  .doc-fullscreen-content :global(h1) {
    font-size: 2em;
    font-weight: 700;
    margin: 0 0 0.6em;
    padding-bottom: 0.3em;
    border-bottom: 1px solid var(--color-grey-25);
    color: var(--color-font-primary);
  }

  .doc-fullscreen-content :global(h2) {
    font-size: 1.5em;
    font-weight: 600;
    margin: 1.5em 0 0.5em;
    padding-bottom: 0.2em;
    border-bottom: 1px solid var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .doc-fullscreen-content :global(h3) {
    font-size: 1.25em;
    font-weight: 600;
    margin: 1.2em 0 0.4em;
    color: var(--color-font-primary);
  }

  .doc-fullscreen-content :global(h4),
  .doc-fullscreen-content :global(h5),
  .doc-fullscreen-content :global(h6) {
    font-size: 1.1em;
    font-weight: 600;
    margin: 1em 0 0.3em;
    color: var(--color-font-primary);
  }

  /* Paragraphs */
  .doc-fullscreen-content :global(p) {
    margin: 0.8em 0;
  }

  /* Lists */
  .doc-fullscreen-content :global(ul),
  .doc-fullscreen-content :global(ol) {
    padding-left: 2em;
    margin: 0.8em 0;
  }

  .doc-fullscreen-content :global(li) {
    margin: 0.3em 0;
  }

  .doc-fullscreen-content :global(li > ul),
  .doc-fullscreen-content :global(li > ol) {
    margin: 0.2em 0;
  }

  /* Blockquotes */
  .doc-fullscreen-content :global(blockquote) {
    border-left: 3px solid var(--color-primary);
    margin: 1em 0;
    padding: 0.5em 1em;
    color: var(--color-font-secondary);
    background: var(--color-grey-15);
    border-radius: 0 6px 6px 0;
  }

  .doc-fullscreen-content :global(blockquote p) {
    margin: 0.3em 0;
  }

  /* Tables */
  .doc-fullscreen-content :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 0.95em;
    overflow-x: auto;
    display: block;
  }

  .doc-fullscreen-content :global(th),
  .doc-fullscreen-content :global(td) {
    border: 1px solid var(--color-grey-25);
    padding: 8px 12px;
    text-align: left;
  }

  .doc-fullscreen-content :global(th) {
    background: var(--color-grey-15);
    font-weight: 600;
  }

  .doc-fullscreen-content :global(tr:nth-child(even)) {
    background: var(--color-grey-10);
  }

  /* Inline code */
  .doc-fullscreen-content :global(code) {
    background: var(--color-grey-15);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.9em;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
  }

  /* Code blocks */
  .doc-fullscreen-content :global(pre) {
    background: var(--color-grey-15);
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 1em 0;
  }

  .doc-fullscreen-content :global(pre code) {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 14px;
    line-height: 1.5;
  }

  /* Links */
  .doc-fullscreen-content :global(a) {
    color: var(--color-primary);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .doc-fullscreen-content :global(a:hover) {
    opacity: 0.8;
  }

  /* Horizontal rules */
  .doc-fullscreen-content :global(hr) {
    border: none;
    border-top: 1px solid var(--color-grey-25);
    margin: 2em 0;
  }

  /* Images */
  .doc-fullscreen-content :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    margin: 1em 0;
  }

  /* Strong and emphasis */
  .doc-fullscreen-content :global(strong) {
    font-weight: 600;
  }

  .doc-fullscreen-content :global(em) {
    font-style: italic;
  }

  /* Definition lists */
  .doc-fullscreen-content :global(dl) {
    margin: 1em 0;
  }

  .doc-fullscreen-content :global(dt) {
    font-weight: 600;
    margin-top: 0.5em;
  }

  .doc-fullscreen-content :global(dd) {
    margin-left: 2em;
    margin-bottom: 0.5em;
  }

  /* Empty state */
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
</style>
