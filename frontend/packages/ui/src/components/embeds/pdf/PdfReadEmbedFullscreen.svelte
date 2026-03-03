<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfReadEmbedFullscreen.svelte

  Fullscreen view for pdf/read skill result embeds.
  Shows the full extracted text content from the PDF pages that were read.

  Architecture:
  - Mounted by ActiveChat.svelte in response to the 'pdfreadfullscreen' CustomEvent.
  - AppSkillUseRenderer and GroupRenderer dispatch that event when the user clicks
    a finished pdf.read embed card.
  - The event carries embedId (the skill-use embed's own ID) so this component can
    receive TOON content updates via onEmbedDataUpdated from UnifiedEmbedFullscreen.
  - Text content comes from results[0].content (markdown stored as plain text).

  Display:
  - Header: filename + "Read" skill label
  - Content: full extracted text in a pre-wrap scrollable text box
    (same visual pattern as VideoTranscriptEmbedFullscreen)
  - Actions: Copy (copies text to clipboard), Download (saves as .txt)

  Event chain:
    PdfReadEmbedPreview (onFullscreen prop)
    → AppSkillUseRenderer / GroupRenderer (dispatches 'pdfreadfullscreen' event)
    → ActiveChat.svelte (handlePdfReadFullscreen → showPdfReadFullscreen = true)
    → this component is mounted with embedId, filename, textContent
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  interface Props {
    /** The skill-use embed's own ID (used by UnifiedEmbedFullscreen for updates) */
    embedId?: string;
    /** Filename of the PDF */
    filename?: string;
    /** Number of pages that were read */
    pagesReturned?: number[];
    /** Number of pages skipped */
    pagesSkipped?: number[];
    /** Full extracted text content (markdown, shown as plain text) */
    textContent?: string;
    /** Close handler */
    onClose: () => void;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of navigation ('previous' | 'next') */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" button to restore chat visibility */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }

  let {
    embedId,
    filename: filenameProp,
    pagesReturned: pagesReturnedProp,
    pagesSkipped: pagesSkippedProp,
    textContent: textContentProp,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Local state — updated via onEmbedDataUpdated when TOON content arrives
  // ---------------------------------------------------------------------------

  let localFilename = $state<string>('');
  let localTextContent = $state<string>('');
  let localPagesReturned = $state<number[]>([]);
  let localPagesSkipped = $state<number[]>([]);

  // Initialize from props
  $effect(() => {
    localFilename = filenameProp || '';
    localTextContent = textContentProp || '';
    localPagesReturned = pagesReturnedProp || [];
    localPagesSkipped = pagesSkippedProp || [];
  });

  /**
   * Handle live embed data updates from UnifiedEmbedFullscreen.
   * Called when the TOON content for the skill embed is decoded.
   * Extracts results[0].content + metadata.
   */
  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
    results?: unknown[];
  }): void {
    console.debug('[PdfReadEmbedFullscreen] Received embed data update:', {
      status: data.status,
      hasContent: !!data.decodedContent,
    });

    const content = data.decodedContent;
    if (!content) return;

    // Extract text content from results[0].content
    const results = content.results as Array<Record<string, unknown>> | undefined;
    const c = results?.[0]?.content as string | undefined;
    if (c) localTextContent = c;

    // Extract filename
    const fn = content.filename as string | undefined;
    if (fn) localFilename = fn;

    // Extract pages_returned + pages_skipped
    const pr = results?.[0]?.pages_returned ?? content.pages_returned;
    if (Array.isArray(pr)) localPagesReturned = pr as number[];
    const ps = results?.[0]?.pages_skipped ?? content.pages_skipped;
    if (Array.isArray(ps)) localPagesSkipped = ps as number[];
  }

  // ---------------------------------------------------------------------------
  // Derived display values
  // ---------------------------------------------------------------------------

  let skillName = $derived($text('app_skills.pdf.read.skill_name') || 'Read');

  /**
   * Display filename — truncated with ellipsis if very long.
   */
  let displayFilename = $derived.by(() => {
    const fn = localFilename;
    if (!fn) return 'PDF';
    if (fn.length > 50) {
      const lastDot = fn.lastIndexOf('.');
      if (lastDot > 0) {
        const ext = fn.slice(lastDot);
        return fn.slice(0, 47 - ext.length) + '\u2026' + ext;
      }
      return fn.slice(0, 47) + '\u2026';
    }
    return fn;
  });

  /**
   * Meta line: "Page N" or "Pages 1–3 · 2 skipped · 10 pages total"
   */
  let metaLine = $derived.by(() => {
    const readCount = localPagesReturned.length;
    const skippedCount = localPagesSkipped.length;
    if (readCount === 0) return '';
    const sorted = [...localPagesReturned].sort((a, b) => a - b);
    const pagesStr = readCount === 1
      ? `Page ${sorted[0]} read`
      : `Pages ${sorted[0]}\u2013${sorted[sorted.length - 1]} read`;
    const skippedStr = skippedCount > 0 ? ` \u00B7 ${skippedCount} skipped` : '';
    return `${pagesStr}${skippedStr}`;
  });

  /**
   * Character + word count summary for header context.
   */
  let charCount = $derived(localTextContent.length);
  let wordCount = $derived(
    localTextContent ? localTextContent.trim().split(/\s+/).filter(Boolean).length : 0
  );

  // ---------------------------------------------------------------------------
  // Copy action
  // ---------------------------------------------------------------------------

  async function handleCopy(): Promise<void> {
    if (!localTextContent) return;
    try {
      await navigator.clipboard.writeText(localTextContent);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.success('Copied to clipboard');
      console.debug('[PdfReadEmbedFullscreen] Copied text to clipboard');
    } catch (err) {
      console.error('[PdfReadEmbedFullscreen] Failed to copy:', err);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to copy to clipboard');
    }
  }

  // ---------------------------------------------------------------------------
  // Download action
  // ---------------------------------------------------------------------------

  function handleDownload(): void {
    if (!localTextContent) return;
    try {
      const blob = new Blob([localTextContent], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const baseName = (localFilename || 'document').replace(/\.pdf$/i, '');
      a.download = `${baseName}_read.txt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      console.debug('[PdfReadEmbedFullscreen] Downloaded text file');
    } catch (err) {
      console.error('[PdfReadEmbedFullscreen] Failed to download:', err);
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="pdf"
  skillId="read"
  embedHeaderTitle={displayFilename}
  embedHeaderSubtitle={skillName}
  skillIconName="book"
  showSkillIcon={true}
  {onClose}
  onCopy={localTextContent ? handleCopy : undefined}
  onDownload={localTextContent ? handleDownload : undefined}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="read-container">
      {#if !localTextContent}
        <!-- No content yet — show placeholder -->
        <div class="no-content">
          <p>No text content available.</p>
        </div>
      {:else}
        <!-- Meta info: pages read + char/word count -->
        {#if metaLine || charCount > 0}
          <div class="content-meta">
            {#if metaLine}
              <span class="meta-pages">{metaLine}</span>
              {#if charCount > 0}<span class="meta-sep">\u00B7</span>{/if}
            {/if}
            {#if wordCount > 0}
              <span class="meta-words">{wordCount.toLocaleString()} words</span>
            {/if}
          </div>
        {/if}

        <!-- Full text content box (same pattern as VideoTranscriptEmbedFullscreen) -->
        <div class="text-box">
          <div class="text-content">{localTextContent}</div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     PDF Read Fullscreen — Layout
     =========================================== */

  .read-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    width: 100%;
    margin-top: 80px;
  }

  .no-content {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }

  /* Meta info row: pages read + word count */
  .content-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    max-width: 722px;
    font-size: 14px;
    font-weight: 600;
    color: var(--color-font-primary);
    padding: 0 4px;
  }

  .meta-sep {
    color: var(--color-grey-50);
  }

  .meta-words {
    color: var(--color-grey-70);
  }

  /* Text content box — matches VideoTranscriptEmbedFullscreen .transcript-box */
  .text-box {
    width: auto;
    max-width: 722px;
    background-color: var(--color-grey-10);
    border-radius: 16px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    padding: 20px;
  }

  /* Plain-text content — selectable, pre-wrap to preserve structure */
  .text-content {
    line-height: 1.75;
    width: 100%;
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
    cursor: text;
    white-space: pre-wrap;
    word-wrap: break-word;
    color: var(--color-grey-100);
    font-size: 14px;
  }

  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }
</style>
