<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfReadEmbedPreview.svelte

  Preview card for the pdf/read skill result embed.
  Shown when the AI executes the pdf.read skill to read text from specific pages.

  Displays:
  - Processing state: PDF icon + "Reading…" subtitle
  - Finished state: first ~150 characters of the extracted text (plain-text snippet)
    displayed in the details area where PDFEmbedPreview shows the page screenshot.
  - Error state: error message

  On click: opens PdfReadEmbedFullscreen (pdfreadfullscreen CustomEvent),
  which shows the full extracted text in a scrollable view.

  Architecture:
  - Mounted by AppSkillUseRenderer.ts when app_id='pdf' and skill_id='read'.
  - textContent is passed by the renderer from decodedContent.results[0].content.
  - onEmbedDataUpdated receives live updates from UnifiedEmbedPreview so the
    snippet updates as soon as the skill result arrives.
  - onFullscreen dispatches 'pdfreadfullscreen' event via AppSkillUseRenderer.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  /**
   * Maximum characters shown in the text snippet preview.
   * Long enough to fill the card; short enough not to overflow.
   */
  const MAX_SNIPPET_LENGTH = 160;

  interface Props {
    /** Unique embed ID for this skill-use embed */
    id: string;
    /** Filename of the PDF (from original upload embed) */
    filename?: string;
    /** Pages returned by the read skill */
    pagesReturned?: number[];
    /** Pages skipped due to token budget */
    pagesSkipped?: number[];
    /** Total page count of the PDF */
    pageCount?: number;
    /** Extracted text content (markdown) from results[0].content */
    textContent?: string;
    /** Processing status of the skill execution */
    status: 'processing' | 'finished' | 'error';
    /** Error message if skill failed */
    error?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /**
     * Called when the user clicks to open fullscreen.
     * Implemented by AppSkillUseRenderer: dispatches 'pdfreadfullscreen' event.
     */
    onFullscreen?: () => void;
  }

  let {
    id,
    filename,
    pagesReturned,
    pagesSkipped,
    pageCount,
    textContent: textContentProp,
    status: statusProp,
    error,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Local state — updated via onEmbedDataUpdated as skill result arrives
  // ---------------------------------------------------------------------------

  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTextContent = $state<string>('');
  let localFilename = $state<string>('');
  let localPagesReturned = $state<number[]>([]);

  // Initialize from props
  $effect(() => {
    localStatus = statusProp;
    localTextContent = textContentProp || '';
    localFilename = filename || '';
    localPagesReturned = pagesReturned || [];
  });

  /**
   * Receive live embed data updates from UnifiedEmbedPreview.
   * Called when the TOON content arrives via WebSocket (status: finished).
   */
  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
  }): void {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status as 'processing' | 'finished' | 'error';
    }
    const content = data.decodedContent;
    if (!content) return;

    // Extract text content — stored in results[0].content
    const results = content.results as Array<Record<string, unknown>> | undefined;
    const c = results?.[0]?.content as string | undefined;
    if (c) localTextContent = c;

    // Extract filename if not already set
    const fn = content.filename as string | undefined;
    if (fn) localFilename = fn;

    // Extract pages_returned
    const pr = results?.[0]?.pages_returned ?? content.pages_returned;
    if (Array.isArray(pr)) localPagesReturned = pr as number[];
  }

  // ---------------------------------------------------------------------------
  // Derived display values
  // ---------------------------------------------------------------------------

  /**
   * i18n skill name shown in the BasicInfosBar header line (e.g. "Read" / "Lesen").
   */
  let skillName = $derived($text('app_skills.pdf.read.skill_name'));

  /**
   * Strip common markdown symbols for clean plain-text preview.
   * Removes: #, *, _, `, >, -, [ ], | table chars, and collapses whitespace.
   */
  function stripMarkdown(md: string): string {
    return md
      .replace(/^#{1,6}\s+/gm, '')   // headings
      .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')  // bold/italic
      .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
      .replace(/`{1,3}[^`]*`{1,3}/g, '')  // code
      .replace(/^\s*[-*+>|]\s*/gm, '')    // list/quote/table chars
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')  // links → label only
      .replace(/\n{2,}/g, ' ')            // collapse blank lines
      .replace(/\s+/g, ' ')
      .trim();
  }

  /**
   * Text snippet: first MAX_SNIPPET_LENGTH chars of stripped text.
   * Falls back to a status description when content is not yet available.
   */
  let snippet = $derived.by(() => {
    if (localStatus === 'processing') return '';
    if (localStatus === 'error') return error || '';
    if (localTextContent) {
      const plain = stripMarkdown(localTextContent);
      if (plain.length <= MAX_SNIPPET_LENGTH) return plain;
      // Break at last space before limit to avoid cutting mid-word
      const cut = plain.slice(0, MAX_SNIPPET_LENGTH);
      const lastSpace = cut.lastIndexOf(' ');
      return (lastSpace > 80 ? cut.slice(0, lastSpace) : cut) + '\u2026';
    }
    // Fallback when no content yet (e.g. older embed without content field)
    const readCount = localPagesReturned.length;
    if (readCount > 0) {
      const sorted = [...localPagesReturned].sort((a, b) => a - b);
      return readCount === 1
        ? `Page ${sorted[0]} read`
        : `${readCount} pages read`;
    }
    return localFilename || 'PDF';
  });

  /** Status text for the customStatusText bar (small subtitle) */
  let statusText = $derived.by(() => {
    if (localStatus === 'processing') return $text('app_skills.pdf.read.processing') || 'Reading\u2026';
    if (localStatus === 'error') return error || '';
    // In finished state: show page range info in the subtitle bar
    const readCount = localPagesReturned.length;
    const skippedCount = pagesSkipped?.length ?? 0;
    const pcStr = pageCount && pageCount > 0
      ? (pageCount === 1 ? ' \u00B7 1 page' : ` \u00B7 ${pageCount} pages`)
      : '';
    if (readCount > 0) {
      const sorted = [...localPagesReturned].sort((a, b) => a - b);
      const pagesStr = readCount === 1 ? `Page ${sorted[0]}` : `Pages ${sorted[0]}\u2013${sorted[sorted.length - 1]}`;
      const skippedStr = skippedCount > 0 ? ` \u00B7 ${skippedCount} skipped` : '';
      return `${pagesStr}${skippedStr}${pcStr}`;
    }
    return pcStr.replace(/^\s*\u00B7\s*/, '') || localFilename || 'PDF';
  });

  /** Show fullscreen button when finished and callback is available */
  let isFullscreenEnabled = $derived(localStatus === 'finished' && !!onFullscreen);
</script>

<!--
  showSkillIcon=false so the PDF icon fills the details snippet area (same as PDFEmbedPreview).
  hasFullWidthImage=false (no screenshot — the text snippet fills the details area instead).
-->
<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="read"
  skillIconName="book"
  status={localStatus}
  {skillName}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  showStatus={true}
  customStatusText={statusText}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="pdf-read-details" class:mobile={isMobileSnippet}>
      {#if localStatus === 'processing'}
        <!--
          Processing: show a single centered book icon while reading is in progress.
          Same visual pattern as PDFEmbedPreview while OCR is running.
        -->
        <div class="icon-center">
          <div class="skill-icon-large book"></div>
        </div>
      {:else if snippet}
        <!--
          Finished: show text snippet in the area where PDFEmbedPreview
          shows the page screenshot. Plain-text, selectable, no markdown.
        -->
        <div class="text-snippet">{snippet}</div>
      {:else}
        <div class="icon-center">
          <div class="skill-icon-large book"></div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .pdf-read-details {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  /* Centered icon fallback (processing / no content) */
  .icon-center {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  /* Large skill icon in the details area — styled like PDFEmbedPreview's PDF icon */
  .skill-icon-large {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    background-size: 26px 26px;
    background-repeat: no-repeat;
    background-position: center;
    background-color: var(--color-grey-20);
    flex-shrink: 0;
  }

  .skill-icon-large.book {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
    background-color: var(--color-grey-60);
  }

  /* Text snippet fills the full details area */
  .text-snippet {
    width: 100%;
    height: 100%;
    padding: 10px 12px;
    box-sizing: border-box;
    font-size: 12px;
    line-height: 1.55;
    color: var(--color-grey-80);
    overflow: hidden;
    /* Show as many lines as fit, clamp with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 6;
    line-clamp: 6;
    -webkit-box-orient: vertical;
    text-overflow: ellipsis;
    word-break: break-word;
    white-space: pre-wrap;
    user-select: none;
  }

  .pdf-read-details.mobile .text-snippet {
    font-size: 11px;
    padding: 8px 10px;
    -webkit-line-clamp: 5;
    line-clamp: 5;
  }

  /* Skill icon: book.svg for pdf.read */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }
</style>
