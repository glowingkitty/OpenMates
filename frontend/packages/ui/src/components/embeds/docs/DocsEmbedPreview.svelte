<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedPreview.svelte
  
  Preview component for Document embeds (document_html).
  Uses UnifiedEmbedPreview as base and provides document-specific details content.
  
  Renders an A4-like document preview with:
  - White page background simulating a Word/Google Docs document
  - Document content rendered with proper typography
  - Filename (e.g. "Report.docx") shown in the bottom bar instead of title
  - Doc icon visible in the bottom bar gradient circle
  
  Sizes:
  - Desktop: 300x200px
  - Mobile: 150x290px
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
        <!-- A4-like document page preview -->
        <div class="doc-page-wrapper">
          <div class="doc-page">
            <div class="doc-page-content">
              <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is sanitized via DOMPurify in sanitizeDocumentHtml() -->
              {@html sanitizedHtml}
            </div>
          </div>
        </div>
      {:else if status === 'processing'}
        <!-- Processing state -->
        <div class="processing-placeholder">
          <div class="doc-page-wrapper">
            <div class="doc-page processing-page">
              <div class="processing-lines">
                <div class="line-placeholder" style="width: 70%"></div>
                <div class="line-placeholder" style="width: 100%"></div>
                <div class="line-placeholder" style="width: 85%"></div>
                <div class="line-placeholder" style="width: 60%"></div>
                <div class="line-placeholder" style="width: 90%"></div>
                <div class="line-placeholder" style="width: 45%"></div>
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
     Document Details Content - A4-like Preview
     =========================================== */
  
  .doc-details {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--color-grey-20);
    border-radius: 4px;
    overflow: hidden;
  }
  
  /* A4 page wrapper - centers the white page with subtle shadow */
  .doc-page-wrapper {
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 8px 12px 4px;
    overflow: hidden;
  }
  
  .doc-details.mobile .doc-page-wrapper {
    padding: 6px 8px 4px;
  }
  
  /* White A4 page simulation */
  .doc-page {
    width: 100%;
    max-width: 240px;
    background: white;
    border-radius: 3px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
    padding: 10px 12px;
    overflow: hidden;
    position: relative;
    max-height: 100%;
  }
  
  .doc-details.mobile .doc-page {
    padding: 6px 8px;
  }
  
  /* Page content - scaled down document rendering */
  .doc-page-content {
    font-size: 7px;
    line-height: 1.4;
    color: #333;
    word-break: break-word;
    overflow: hidden;
    max-height: 100%;
  }
  
  .doc-details.mobile .doc-page-content {
    font-size: 5.5px;
    line-height: 1.3;
  }
  
  /* Document preview typography - compact for small A4 page preview */
  .doc-page-content :global(h1) {
    font-size: 10px;
    font-weight: 700;
    margin: 0 0 4px;
    color: #111;
  }

  .doc-page-content :global(h2) {
    font-size: 9px;
    font-weight: 600;
    margin: 4px 0 3px;
    color: #222;
  }

  .doc-page-content :global(h3),
  .doc-page-content :global(h4),
  .doc-page-content :global(h5),
  .doc-page-content :global(h6) {
    font-size: 8px;
    font-weight: 600;
    margin: 3px 0 2px;
    color: #333;
  }
  
  .doc-page-content :global(p) {
    margin: 0 0 3px;
  }
  
  .doc-page-content :global(ul),
  .doc-page-content :global(ol) {
    margin: 0 0 3px;
    padding-left: 10px;
  }
  
  .doc-page-content :global(li) {
    margin: 0 0 1px;
  }
  
  .doc-page-content :global(blockquote) {
    margin: 0 0 3px;
    padding: 2px 4px;
    border-left: 1.5px solid #ccc;
    color: #666;
    font-style: italic;
  }
  
  .doc-page-content :global(table) {
    font-size: 6px;
    border-collapse: collapse;
    margin: 0 0 3px;
    width: 100%;
  }
  
  .doc-page-content :global(th),
  .doc-page-content :global(td) {
    padding: 1px 2px;
    border: 0.5px solid #ddd;
  }

  .doc-page-content :global(th) {
    background: #f5f5f5;
    font-weight: 600;
  }
  
  .doc-page-content :global(code) {
    font-size: 6px;
    background: #f5f5f5;
    padding: 0 2px;
    border-radius: 1px;
  }
  
  .doc-page-content :global(pre) {
    font-size: 6px;
    background: #f5f5f5;
    padding: 3px;
    border-radius: 2px;
    overflow: hidden;
    margin: 0 0 3px;
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
    border-top: 0.5px solid #ddd;
    margin: 3px 0;
  }
  
  .doc-page-content :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 2px;
  }
  
  /* ===========================================
     Processing State - Skeleton A4 page
     =========================================== */
  
  .processing-placeholder {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  
  .processing-page {
    display: flex;
    align-items: flex-start;
  }
  
  .processing-lines {
    display: flex;
    flex-direction: column;
    gap: 5px;
    width: 100%;
    padding: 2px 0;
  }
  
  .line-placeholder {
    height: 4px;
    background: #e0e0e0;
    border-radius: 2px;
    animation: shimmer-line 1.5s infinite ease-in-out;
  }
  
  .line-placeholder:nth-child(1) { animation-delay: 0s; }
  .line-placeholder:nth-child(2) { animation-delay: 0.1s; }
  .line-placeholder:nth-child(3) { animation-delay: 0.2s; }
  .line-placeholder:nth-child(4) { animation-delay: 0.3s; }
  .line-placeholder:nth-child(5) { animation-delay: 0.4s; }
  .line-placeholder:nth-child(6) { animation-delay: 0.5s; }
  
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
