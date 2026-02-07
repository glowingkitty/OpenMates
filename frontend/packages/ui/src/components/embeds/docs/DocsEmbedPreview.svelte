<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedPreview.svelte
  
  Preview component for Document embeds (document_html).
  Uses UnifiedEmbedPreview as base and provides document-specific details content.
  
  Renders an A4-like document preview using CSS transform: scale() to shrink a
  full-sized document page into the preview card. This ensures the preview is
  an exact miniature of the fullscreen view.
  
  Sizes:
  - Desktop: 300x200px (preview card)
  - Mobile: 150x290px (preview card)
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import {
    sanitizeDocumentHtml,
    extractDocumentTitle,
    extractDocumentFilename,
    generateFilenameFromTitle,
    countDocWords
  } from './docsEmbedContent';
  
  /**
   * Props for document embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Document title */
    title?: string;
    /** Document filename (e.g. "Report.docx") */
    filename?: string;
    /** Number of words in the document */
    wordCount?: number;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
    /** HTML content (full HTML for preview extraction) */
    htmlContent?: string;
  }
  
  let {
    id,
    title: titleProp,
    filename: filenameProp,
    wordCount: wordCountProp = 0,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen,
    htmlContent: htmlContentProp = ''
  }: Props = $props();
  
  // Local reactive state for embed data - updated via onEmbedDataUpdated callback
  let localHtmlContent = $state<string>('');
  let localTitle = $state<string | undefined>(undefined);
  let localFilename = $state<string | undefined>(undefined);
  let localWordCount = $state<number>(0);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localHtmlContent = htmlContentProp || '';
    localTitle = titleProp;
    localFilename = filenameProp;
    localWordCount = wordCountProp || 0;
    localStatus = statusProp || 'processing';
    localTaskId = taskIdProp;
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let htmlContent = $derived(localHtmlContent);
  let title = $derived(localTitle);
  let filename = $derived(localFilename);
  let wordCount = $derived(localWordCount);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);
  
  // Sanitize HTML content for safe rendering in preview
  let sanitizedHtml = $derived(sanitizeDocumentHtml(htmlContent));
  
  // Extract title from content if not provided via props
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
  
  /**
   * Decoded content structure from embed data updates
   */
  interface DecodedDocContent {
    html?: string;
    title?: string;
    filename?: string;
    word_count?: number;
    task_id?: string;
  }

  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   * This enables real-time updates during streaming
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: DecodedDocContent | null }) {
    console.debug(`[DocsEmbedPreview] Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent,
      hasHtml: !!data.decodedContent?.html
    });
    
    if (data.decodedContent) {
      if (data.decodedContent.html !== undefined) {
        localHtmlContent = data.decodedContent.html || '';
      }
      if (data.decodedContent.title !== undefined) {
        localTitle = data.decodedContent.title;
      }
      if (data.decodedContent.filename !== undefined) {
        localFilename = data.decodedContent.filename;
      }
      if (data.decodedContent.word_count !== undefined) {
        localWordCount = data.decodedContent.word_count || 0;
      }
      if (data.decodedContent.task_id !== undefined) {
        localTaskId = data.decodedContent.task_id;
      }
    }
    
    if (data.status) {
      localStatus = data.status as 'processing' | 'finished' | 'error';
    }
  }
  
  // Handle stop button click (not applicable for documents, but included for API consistency)
  async function handleStop() {
    console.debug('[DocsEmbedPreview] Stop requested (not applicable for documents)');
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="docs"
  skillId="doc"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="doc-details" class:mobile={isMobileLayout}>
      {#if sanitizedHtml}
        <!--
          A4-like document preview using CSS transform: scale().
          We render the document at full size (816px wide, same as fullscreen)
          inside a container, then scale it down to fit the preview card.
          This creates an exact miniature of the fullscreen document view.
        -->
        <div class="doc-page-viewport">
          <div class="doc-page-scaler">
            <div class="doc-page">
              <div class="doc-page-content">
                <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is sanitized via DOMPurify in sanitizeDocumentHtml() -->
                {@html sanitizedHtml}
              </div>
            </div>
          </div>
        </div>
      {:else if status === 'processing'}
        <!-- Processing state - skeleton A4 page -->
        <div class="doc-page-viewport">
          <div class="doc-page-scaler">
            <div class="doc-page processing-page">
              <div class="processing-lines">
                <div class="line-placeholder" style="width: 60%"></div>
                <div class="line-spacer"></div>
                <div class="line-placeholder" style="width: 100%"></div>
                <div class="line-placeholder" style="width: 95%"></div>
                <div class="line-placeholder" style="width: 80%"></div>
                <div class="line-placeholder" style="width: 100%"></div>
                <div class="line-placeholder" style="width: 70%"></div>
                <div class="line-spacer"></div>
                <div class="line-placeholder heading" style="width: 45%"></div>
                <div class="line-placeholder" style="width: 100%"></div>
                <div class="line-placeholder" style="width: 88%"></div>
              </div>
            </div>
          </div>
        </div>
      {:else}
        <!-- Error/empty state -->
        <div class="empty-placeholder">
          <div class="doc-icon" data-skill-icon="docs"></div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Document Details - A4-like scaled preview
     
     Strategy: Render the document at full size
     (816px width, matching the fullscreen view)
     then use CSS transform: scale() to shrink it
     into the preview card. This creates an exact
     miniature that matches the fullscreen layout.
     =========================================== */
  
  .doc-details {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--color-grey-20);
    overflow: hidden;
  }
  
  /* Viewport clips the scaled page to the preview size */
  .doc-page-viewport {
    flex: 1;
    min-height: 0;
    overflow: hidden;
    position: relative;
  }
  
  /* Scaler: holds the full-size page and applies transform: scale() */
  /* Desktop preview is ~276px wide (300 - padding), so scale = 276/816 ≈ 0.338 */
  .doc-page-scaler {
    width: 816px;
    transform: scale(0.338);
    transform-origin: top left;
  }
  
  .doc-details.mobile .doc-page-scaler {
    /* Mobile preview is ~126px wide (150 - padding), scale = 126/816 ≈ 0.155 */
    transform: scale(0.155);
  }
  
  /* White A4 page - same styling as fullscreen for exact match */
  .doc-page {
    width: 100%;
    background: white;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
    border-radius: 4px;
    padding: 56px 72px 72px;
    min-height: 600px;
  }
  
  /* Page content - full-size typography matching fullscreen */
  .doc-page-content {
    color: #1a1a1a;
    font-size: 15px;
    line-height: 1.75;
    word-break: break-word;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  }
  
  /* Document typography - matches DocsEmbedFullscreen exactly */
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

  .doc-page-content :global(h3),
  .doc-page-content :global(h4),
  .doc-page-content :global(h5),
  .doc-page-content :global(h6) {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 8px;
    color: #1a1a1a;
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
  
  .doc-page-content :global(blockquote) {
    border-left: 3px solid #1a73e8;
    margin: 16px 0;
    padding: 8px 16px;
    color: #555;
    background: #f8f9fa;
    border-radius: 0 4px 4px 0;
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
  }
  
  .doc-page-content :global(code) {
    background: #f1f3f4;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
  }
  
  .doc-page-content :global(pre) {
    background: #f8f9fa;
    padding: 16px 20px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
    border: 1px solid #e8eaed;
  }
  
  .doc-page-content :global(a) {
    color: #1a73e8;
    text-decoration: none;
  }
  
  .doc-page-content :global(strong),
  .doc-page-content :global(b) {
    font-weight: 600;
  }
  
  .doc-page-content :global(em),
  .doc-page-content :global(i) {
    font-style: italic;
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
  }
  
  /* ===========================================
     Processing State - Skeleton A4 page
     =========================================== */
  
  .processing-page {
    display: flex;
    align-items: flex-start;
  }
  
  .processing-lines {
    display: flex;
    flex-direction: column;
    gap: 14px;
    width: 100%;
  }
  
  .line-placeholder {
    height: 12px;
    background: #e8e8e8;
    border-radius: 6px;
    animation: shimmer-line 1.5s infinite ease-in-out;
  }
  
  .line-placeholder.heading {
    height: 20px;
    background: #ddd;
  }
  
  .line-spacer {
    height: 8px;
  }
  
  .line-placeholder:nth-child(1) { animation-delay: 0s; }
  .line-placeholder:nth-child(2) { animation-delay: 0.1s; }
  .line-placeholder:nth-child(3) { animation-delay: 0.15s; }
  .line-placeholder:nth-child(4) { animation-delay: 0.2s; }
  .line-placeholder:nth-child(5) { animation-delay: 0.25s; }
  .line-placeholder:nth-child(6) { animation-delay: 0.3s; }
  .line-placeholder:nth-child(7) { animation-delay: 0.35s; }
  .line-placeholder:nth-child(8) { animation-delay: 0.4s; }
  .line-placeholder:nth-child(9) { animation-delay: 0.45s; }
  .line-placeholder:nth-child(10) { animation-delay: 0.5s; }
  .line-placeholder:nth-child(11) { animation-delay: 0.55s; }
  
  @keyframes shimmer-line {
    0%, 100% {
      opacity: 0.4;
    }
    50% {
      opacity: 0.8;
    }
  }
  
  /* ===========================================
     Empty/Error State
     =========================================== */
  
  .empty-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-font-tertiary);
  }
  
  .empty-placeholder .doc-icon {
    width: 48px;
    height: 48px;
    opacity: 0.3;
    background-color: var(--color-font-tertiary);
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  :global(.unified-embed-preview .skill-icon[data-skill-icon="docs"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="docs"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }
</style>
