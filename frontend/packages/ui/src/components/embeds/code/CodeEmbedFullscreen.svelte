<!--
  frontend/packages/ui/src/components/embeds/CodeEmbedFullscreen.svelte
  
  Fullscreen view for Code embeds.
  Uses UnifiedEmbedFullscreen as base and provides code-specific content.
  
  Shows:
  - Code filename, language, and line count in header
  - Full syntax-highlighted code (scrollable)
  - Copy button to copy code to clipboard
  - Basic infos bar at the bottom
-->

<script lang="ts">
  import { onMount } from 'svelte';
  // Import highlight.js theme - using github-dark for dark mode compatibility
  import 'highlight.js/styles/github-dark.css';
  // Import shared highlighting utilities (includes all language support + Svelte)
  import { highlightToLines } from './codeHighlighting';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { downloadCodeFile } from '../../../services/zipExportService';
  import { notificationStore } from '../../../stores/notificationStore';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from './codeEmbedContent';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import type { PIIMapping } from '../../../types/chat';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { codeLineHighlightStore } from '../../../stores/messageHighlightStore';
  
  /**
   * Props for code embed fullscreen
   */
  interface Props {
    /** Programming language */
    language?: string;
    /** Filename */
    filename?: string;
    /** Number of lines in the code */
    lineCount?: number;
    /** Code content (full code) */
    codeContent: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of navigation ('previous' | 'next') — set transiently during prev/next transitions */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" button to restore chat visibility (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
    /**
     * PII mappings from the parent chat — maps placeholder strings (e.g. "[EMAIL_1]")
     * to original values. When provided and piiRevealed is true, placeholder strings
     * in the code content are replaced with originals for display.
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
    language = '',
    filename,
    lineCount = 0,
    codeContent,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    piiMappings = [],
    piiRevealed = false
  }: Props = $props();

  // Local PII reveal toggle — initialised to false; synced from prop via $effect below.
  let localPiiRevealed = $state(false);

  // Keep localPiiRevealed in sync when the parent prop changes.
  $effect(() => {
    localPiiRevealed = piiRevealed;
  });

  /** Whether there are any PII mappings to apply (controls button visibility) */
  let hasPII = $derived(piiMappings.length > 0);

  function togglePII() {
    localPiiRevealed = !localPiiRevealed;
  }
  
  /**
   * Apply PII masking to the raw code string before parsing/displaying.
   * The AI-generated code may include placeholder strings (e.g. "[EMAIL_1]").
   * When localPiiRevealed is true, restore originals; otherwise keep placeholders.
   */
  let piiProcessedCodeContent = $derived.by(() => {
    if (!hasPII || !codeContent) return codeContent;
    if (localPiiRevealed) {
      return restorePIIInText(codeContent, piiMappings);
    } else {
      return replacePIIOriginalsWithPlaceholders(codeContent, piiMappings);
    }
  });

  // Parse code content to extract language, filename, and actual code
  let parsedContent = $derived.by(() => parseCodeEmbedContent(piiProcessedCodeContent, { language, filename }));
  let renderCodeContent = $derived(parsedContent.code);
  let renderLanguage = $derived(parsedContent.language || '');
  let renderFilename = $derived(parsedContent.filename);
  let displayLanguage = $derived.by(() => formatLanguageName(renderLanguage));
  
  // Calculate actual line count from content if not provided
  let actualLineCount = $derived.by(() => {
    if (lineCount > 0) return lineCount;
    return countCodeLines(renderCodeContent);
  });

  /**
   * Per-line highlighted HTML fragments.
   * Re-computed whenever the code content or language changes.
   * Each element is a sanitized HTML string for one source line.
   */
  let highlightedLines = $derived(highlightToLines(renderCodeContent, renderLanguage));

  /**
   * The line range to highlight, sourced from the global codeLineHighlightStore.
   * Set when the user clicks an embed: link with a #L42 / #L10-L20 suffix.
   * Null when no line highlighting is requested.
   * $codeLineHighlightStore uses Svelte's auto-subscribe rune syntax — it
   * reactively re-evaluates anywhere it is referenced in this component.
   */
  let highlightRange = $derived($codeLineHighlightStore);

  /**
   * Reference to the code lines container — used to query-select the first
   * highlighted line element for auto-scrolling.
   */
  let codeLinesContainer: HTMLElement | null = $state(null);

  /**
   * Scroll the first highlighted line into view (centered).
   * Safe to call before the DOM is rendered — does nothing if container is null.
   */
  function scrollToHighlightedLine() {
    if (!codeLinesContainer || !highlightRange) return;
    const startLine = codeLinesContainer.querySelector(
      `.code-line[data-line="${highlightRange.start}"]`
    ) as HTMLElement | null;
    if (startLine) {
      startLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  // Auto-scroll to the first highlighted line after mount.
  onMount(() => {
    scrollToHighlightedLine();
  });

  // Also scroll whenever the highlight range changes while the fullscreen is open.
  $effect(() => {
    // Reactive dependency on highlightRange — re-runs when the store value changes.
    void highlightRange;
    scrollToHighlightedLine();
  });
  
  // Build skill name for BasicInfosBar: filename (or "Code snippet")
  let skillName = $derived.by(() => {
    // If filename is provided, extract just the filename from path if needed
    const effectiveFilename = renderFilename;
    if (effectiveFilename) {
      // Extract filename from filepath (handle both forward and backslash paths)
      const pathParts = effectiveFilename.split(/[/\\]/);
      return pathParts[pathParts.length - 1];
    }
    // If no filename provided, use translation for "Code snippet"
    return $text('embeds.code_snippet');
  });
  
  // Build status text: line count + language (always use code_info.text format)
  let statusText = $derived.by(() => {
    const lineCount = actualLineCount;
    if (lineCount === 0) return '';
    
    // Build line count text with proper singular/plural handling
    const lineCountText = lineCount === 1 
      ? $text('embeds.code_line_singular')
      : $text('embeds.code_line_plural');
    
    const languageToShow = displayLanguage;
    return languageToShow ? `${lineCount} ${lineCountText}, ${languageToShow}` : `${lineCount} ${lineCountText}`;
  });
  
  // Map skillId to icon name
  const skillIconName = 'coding';
  
  // Handle copy code to clipboard.
  // Copies the PII-processed content (original values if revealed, placeholders if hidden).
  async function handleCopy() {
    try {
      const result = await copyToClipboard(renderCodeContent);
      if (!result.success) throw new Error(result.error || 'Copy failed');
      console.debug('[CodeEmbedFullscreen] Copied code to clipboard');
      notificationStore.success('Code copied to clipboard');
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to copy code:', error);
      notificationStore.error('Failed to copy code to clipboard');
    }
  }

  // Handle download code file
  async function handleDownload() {
    try {
      console.debug('[CodeEmbedFullscreen] Starting code file download');
      await downloadCodeFile(renderCodeContent, renderLanguage, renderFilename);
      notificationStore.success('Code file downloaded successfully');
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to download code file:', error);
      notificationStore.error('Failed to download code file');
    }
  }

  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
  
</script>

<!-- 
  Pass BasicInfosBar props to UnifiedEmbedFullscreen for consistent bottom bar
  Code embeds show: filename + line count/language info
-->
<UnifiedEmbedFullscreen
  appId="code"
  skillId="code"
  embedHeaderTitle={skillName}
  embedHeaderSubtitle={statusText || undefined}
  skillIconName={skillIconName}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    {#if renderCodeContent}
      <!-- Full code with syntax highlighting -->
      <div class="code-fullscreen-container">
        {#if hasPII}
          <!-- PII reveal toggle bar -->
          <div class="code-pii-bar">
            <button
              class="pii-toggle-btn"
              class:pii-toggle-active={localPiiRevealed}
              onclick={togglePII}
              aria-label={localPiiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              title={localPiiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
            >
              {#if localPiiRevealed}
                <!-- Eye-off icon: click to hide -->
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                  <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
              {:else}
                <!-- Eye icon: click to reveal -->
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
              {/if}
              <span class="pii-toggle-label">
                {localPiiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              </span>
            </button>
          </div>
        {/if}
        <!-- Per-line code display — each line is a flex row: gutter number + code text.
             This structure enables GitHub-style per-line highlighting via a background
             bar that spans the full width, without affecting text selection or wrapping.
             data-line attribute (1-indexed) is used by the auto-scroll logic. -->
        <div class="code-lines-container" role="presentation" bind:this={codeLinesContainer}>
          {#each highlightedLines as lineHtml, i}
            {@const lineNum = i + 1}
            {@const isHighlighted = highlightRange != null && lineNum >= highlightRange.start && lineNum <= highlightRange.end}
            <div
              class="code-line"
              class:code-line--highlighted={isHighlighted}
              data-line={lineNum}
            >
              <span class="code-line-gutter" aria-hidden="true">{lineNum}</span>
              <!-- eslint-disable-next-line svelte/no-at-html-tags -->
              <code class="code-line-text">{@html lineHtml}</code>
            </div>
          {/each}
        </div>
      </div>
    {:else}
      <!-- Empty state -->
      <div class="empty-state">
        <p>No code content available.</p>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* Code fullscreen container */
  .code-fullscreen-container {
    width: calc(100% - 10px);
    background-color: var(--color-grey-15);
    margin-top: 70px;
    padding-bottom: 16px;
    margin-left: 10px;
    margin-right: 10px;
  }

  /* PII toggle bar — shown above the code when PII mappings exist */
  .code-pii-bar {
    display: flex;
    align-items: center;
    padding: 6px 0 8px;
  }

  .pii-toggle-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 6px;
    border: none;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
    cursor: pointer;
    font-size: 12px;
    font-weight: 500;
    transition: background-color 0.15s, color 0.15s;
  }

  .pii-toggle-btn:hover {
    background: var(--color-grey-30);
    color: var(--color-font-primary);
  }

  .pii-toggle-btn.pii-toggle-active {
    background: var(--color-warning-subtle, rgba(255, 165, 0, 0.15));
    color: var(--color-warning, #e07b00);
  }

  .pii-toggle-btn.pii-toggle-active:hover {
    background: var(--color-warning-subtle-hover, rgba(255, 165, 0, 0.25));
  }

  .pii-toggle-label {
    font-size: 12px;
  }

  /* Per-line container — vertical stack of .code-line rows.
     overflow-x on the container allows horizontal scrolling for long lines
     while keeping line highlighting at the full container width. */
  .code-lines-container {
    width: 100%;
    overflow-x: auto;
    font-size: 14px;
    line-height: 1.6;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
  }

  /* Each line row: gutter number on the left, code text on the right. */
  .code-line {
    display: flex;
    align-items: baseline;
    min-width: max-content; /* prevents line from wrapping when container scrolls */
    position: relative;
  }

  /* GitHub-style line highlight — full-width yellow background bar.
     Applied to every line inside the requested range. */
  .code-line--highlighted {
    background-color: rgba(255, 200, 50, 0.18);
    border-left: 2px solid rgba(255, 200, 50, 0.7);
  }

  /* Gutter: right-aligned line numbers, not selectable. */
  .code-line-gutter {
    flex: 0 0 auto;
    min-width: 40px;
    padding-right: 12px;
    text-align: right;
    color: var(--color-font-tertiary);
    user-select: none;
    -webkit-user-select: none;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
  }

  /* Code text: allows text selection, no wrapping (container scrolls instead). */
  .code-line-text {
    flex: 1 1 auto;
    display: block;
    white-space: pre;
    color: var(--color-font-primary);
    background: transparent;
    padding: 0;
    margin: 0;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
    user-select: text;
    -webkit-user-select: text;
  }

  /* Syntax highlighting colors — delegated to highlight.js github-dark theme spans */
  .code-line-text :global(.keyword) {
    color: var(--color-syntax-keyword, #c678dd);
  }

  .code-line-text :global(.string) {
    color: var(--color-syntax-string, #98c379);
  }

  .code-line-text :global(.comment) {
    color: var(--color-syntax-comment, #5c6370);
  }

  .code-line-text :global(.function) {
    color: var(--color-syntax-function, #61afef);
  }

  .code-line-text :global(.number) {
    color: var(--color-syntax-number, #d19a66);
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
