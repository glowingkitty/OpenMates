<!--
  frontend/packages/ui/src/components/embeds/docs/DocsEmbedPreview.svelte
  
  Preview component for Document embeds (document_html).
  Uses UnifiedEmbedPreview as base and provides document-specific details content.
  
  Details content structure:
  - Processing: "Generating document..." placeholder with pulsing dot
  - Finished: Rendered HTML preview (first portion of document with styling)
  - Error: Empty placeholder with document icon
  
  Sizes:
  - Desktop: 300x200px
  - Mobile: 150x290px
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { sanitizeDocumentHtml, extractDocumentTitle, countDocWords } from './docsEmbedContent';
  
  /**
   * Props for document embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Document title */
    title?: string;
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
  let localWordCount = $state<number>(0);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localHtmlContent = htmlContentProp || '';
    localTitle = titleProp;
    localWordCount = wordCountProp || 0;
    localStatus = statusProp || 'processing';
    localTaskId = taskIdProp;
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let htmlContent = $derived(localHtmlContent);
  let title = $derived(localTitle);
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
  
  // Calculate word count from content if not provided
  let actualWordCount = $derived.by(() => {
    if (wordCount > 0) return wordCount;
    return countDocWords(htmlContent);
  });
  
  // Build skill name for BasicInfosBar: document title
  let skillName = $derived(displayTitle);
  
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
        <!-- Document preview with rendered HTML (truncated via CSS) -->
        <div class="doc-preview-container">
          <div class="doc-preview-content">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is sanitized via DOMPurify in sanitizeDocumentHtml() -->
            {@html sanitizedHtml}
          </div>
          <div class="doc-preview-fade"></div>
        </div>
      {:else if status === 'processing'}
        <!-- Processing state -->
        <div class="processing-placeholder">
          <span class="processing-dot"></span>
          <span class="processing-text">{$text('embeds.document_generating.text')}</span>
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
     Document Details Content
     =========================================== */
  
  .doc-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    background: transparent;
  }
  
  /* Desktop layout: vertically centered content */
  .doc-details:not(.mobile) {
    justify-content: flex-start;
    padding-top: 4px;
  }
  
  /* Mobile layout: top-aligned content */
  .doc-details.mobile {
    justify-content: flex-start;
  }
  
  /* Document preview container */
  .doc-preview-container {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: transparent;
  }
  
  /* Rendered HTML content preview */
  .doc-preview-content {
    margin: 0;
    padding: 0;
    font-size: 11px;
    line-height: 1.5;
    overflow: hidden;
    color: var(--color-font-secondary);
    word-break: break-word;
    max-height: 100%;
  }
  
  /* Fade overlay at bottom to indicate more content */
  .doc-preview-fade {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 24px;
    background: linear-gradient(to bottom, transparent, var(--color-grey-15));
    pointer-events: none;
  }
  
  .doc-details.mobile .doc-preview-content {
    font-size: 10px;
    line-height: 1.4;
  }
  
  /* Document preview typography - compact for small preview */
  .doc-preview-content :global(h1),
  .doc-preview-content :global(h2),
  .doc-preview-content :global(h3),
  .doc-preview-content :global(h4),
  .doc-preview-content :global(h5),
  .doc-preview-content :global(h6) {
    font-size: 12px;
    font-weight: 600;
    margin: 0 0 4px;
    color: var(--color-font-primary);
  }
  
  .doc-preview-content :global(p) {
    margin: 0 0 6px;
  }
  
  .doc-preview-content :global(ul),
  .doc-preview-content :global(ol) {
    margin: 0 0 6px;
    padding-left: 16px;
  }
  
  .doc-preview-content :global(li) {
    margin: 0 0 2px;
  }
  
  .doc-preview-content :global(blockquote) {
    margin: 0 0 6px;
    padding: 4px 8px;
    border-left: 2px solid var(--color-grey-30);
    color: var(--color-font-tertiary);
    font-style: italic;
  }
  
  .doc-preview-content :global(table) {
    font-size: 10px;
    border-collapse: collapse;
    margin: 0 0 6px;
  }
  
  .doc-preview-content :global(th),
  .doc-preview-content :global(td) {
    padding: 2px 4px;
    border: 1px solid var(--color-grey-25);
  }
  
  .doc-preview-content :global(code) {
    font-size: 10px;
    background: var(--color-grey-20);
    padding: 1px 3px;
    border-radius: 2px;
  }
  
  .doc-preview-content :global(pre) {
    font-size: 10px;
    background: var(--color-grey-20);
    padding: 4px;
    border-radius: 4px;
    overflow: hidden;
    margin: 0 0 6px;
  }
  
  .doc-preview-content :global(a) {
    color: var(--color-primary);
    text-decoration: none;
  }
  
  .doc-preview-content :global(strong),
  .doc-preview-content :global(b) {
    font-weight: 600;
  }
  
  .doc-preview-content :global(em),
  .doc-preview-content :global(i) {
    font-style: italic;
  }
  
  .doc-preview-content :global(hr) {
    border: none;
    border-top: 1px solid var(--color-grey-25);
    margin: 6px 0;
  }
  
  .doc-preview-content :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
  }
  
  .processing-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 8px;
    color: var(--color-font-secondary);
  }
  
  .processing-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background-color: var(--color-primary);
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  .processing-text {
    font-size: 12px;
  }
  
  @keyframes pulse {
    0%, 100% {
      opacity: 0.5;
      transform: scale(0.9);
    }
    50% {
      opacity: 1;
      transform: scale(1);
    }
  }
  
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
