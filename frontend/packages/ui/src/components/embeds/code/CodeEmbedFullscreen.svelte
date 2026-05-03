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
  import { piiVisibilityStore } from '../../../stores/piiVisibilityStore';
  import type { PIIMapping } from '../../../types/chat';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { codeLineHighlightStore } from '../../../stores/messageHighlightStore';
  import CodePreviewPane from './CodePreviewPane.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';

  /**
   * Props for code embed fullscreen
   */
  interface Props {
    /** Standardized raw embed data (decodedContent, attrs, embedData) */
    data: EmbedFullscreenRawData;
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
     * PII mappings from the parent chat — maps placeholder strings (e.g. "[EMAIL_com]")
     * to original values. When provided and piiRevealed is true, placeholder strings
     * in the code content are replaced with originals for display.
     */
    piiMappings?: PIIMapping[];
    /**
     * Whether PII originals are currently visible.
     * When false (default), placeholder strings like [EMAIL_com] are shown as-is.
     * When true, placeholders are replaced with original values.
     * This is the initial value — the user can toggle locally in fullscreen.
     */
    piiRevealed?: boolean;
    /** Current chat ID — required for piiVisibilityStore.toggle(chatId). See OPE-400. */
    chatId?: string;
  }

  let {
    data,
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
    piiRevealed = false,
    chatId
  }: Props = $props();

  // ── Extract fields from data.decodedContent (with attrs fallback) ───────────

  let dc = $derived(data.decodedContent);
  let attrs = $derived(data.attrs);
  let codeContent = $derived(
      typeof dc.code === 'string' ? dc.code
      : typeof attrs?.code === 'string' ? attrs.code as string
      : ''
    );
  let language = $derived(
      typeof dc.language === 'string' ? dc.language
      : typeof attrs?.language === 'string' ? attrs.language as string
      : ''
    );
  let filename = $derived(
      typeof dc.filename === 'string' ? dc.filename
      : typeof attrs?.filename === 'string' ? attrs.filename as string
      : undefined
    );
  let lineCount = $derived(
      typeof dc.line_count === 'number' ? dc.line_count
      : typeof dc.lineCount === 'number' ? dc.lineCount
      : typeof attrs?.lineCount === 'number' ? attrs.lineCount as number
      : 0
    );
  let versionNumber = $derived(
      typeof dc.version_number === 'number' ? dc.version_number
      : data.embedData?.version_number ?? 1
    );

  // Single source of truth: piiRevealed flows down from piiVisibilityStore via
  // the parent (ActiveChat); togglePII() writes back to the same store so the
  // chat header and embed fullscreen stay in sync. See OPE-400.
  /** Whether there are any PII mappings to apply (controls button visibility) */
  let hasPII = $derived(piiMappings.length > 0);

  function togglePII() {
    if (!chatId) return;
    piiVisibilityStore.toggle(chatId);
  }

  /**
   * Apply PII masking to the raw code string before parsing/displaying.
   * When piiRevealed is true, restore originals; otherwise keep placeholders.
   */
  let piiProcessedCodeContent = $derived.by(() => {
    if (!hasPII || !codeContent) return codeContent;
    if (piiRevealed) {
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

  // ── Preview/Render mode ─────────────────────────────────────────────

  /** Languages that support preview rendering. */
  const PREVIEWABLE_LANGUAGES = new Set(['markdown', 'md', 'html', 'htm', 'xml']);

  /** File extensions that support preview rendering. */
  const PREVIEWABLE_EXTENSIONS = new Set(['.md', '.markdown', '.html', '.htm']);

  /**
   * Whether this code embed supports preview rendering.
   * True for markdown/HTML content (detected by language or filename extension).
   */
  let isPreviewable = $derived.by(() => {
    if (PREVIEWABLE_LANGUAGES.has(renderLanguage.toLowerCase())) return true;
    if (renderFilename) {
      const ext = renderFilename.slice(renderFilename.lastIndexOf('.')).toLowerCase();
      if (PREVIEWABLE_EXTENSIONS.has(ext)) return true;
    }
    return false;
  });

  /**
   * Determine the preview type based on language/filename.
   * Returns 'markdown' or 'html'.
   */
  let previewType = $derived.by(() => {
    const lang = renderLanguage.toLowerCase();
    if (lang === 'markdown' || lang === 'md') return 'markdown' as const;
    if (renderFilename) {
      const ext = renderFilename.slice(renderFilename.lastIndexOf('.')).toLowerCase();
      if (ext === '.md' || ext === '.markdown') return 'markdown' as const;
    }
    return 'html' as const;
  });

  /** Whether preview mode is currently active (toggled by the preview button). */
  let previewActive = $state(false);

  function togglePreview() {
    previewActive = !previewActive;
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
  showPreview={isPreviewable}
  {previewActive}
  onTogglePreview={togglePreview}
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
      <!-- Split-pane layout when preview is active, full code otherwise -->
      <div class="code-fullscreen-container" class:preview-split={previewActive}>
        {#if hasPII}
          <!-- PII reveal toggle bar -->
          <div class="code-pii-bar">
            <button
              data-testid="embed-pii-toggle"
              data-pii-revealed={piiRevealed ? 'true' : 'false'}
              class="pii-toggle-btn"
              class:pii-toggle-active={piiRevealed}
              onclick={togglePII}
              aria-label={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              title={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
            >
              {#if piiRevealed}
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
                {piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              </span>
            </button>
          </div>
        {/if}

        <div class="code-split-wrapper" class:split-active={previewActive}>
          <!-- Code panel — always visible. When preview is active, takes 50% on desktop,
               or becomes a shortened scrollable container on mobile. -->
          <div class="code-panel" class:code-panel-split={previewActive}>
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

          <!-- Preview panel — only rendered when preview mode is active -->
          {#if previewActive}
            <div class="preview-panel">
              <CodePreviewPane code={renderCodeContent} {previewType} />
            </div>
          {/if}
        </div>
      </div>
    {:else}
      <!-- Empty state -->
      <div class="empty-state">
        <p>No code content available.</p>
      </div>
    {/if}

    <!-- Version timeline (shown when embed has been edited via diff) -->
    {#if embedId && versionNumber > 1}
      <EmbedVersionTimeline
        {embedId}
        currentVersion={versionNumber}
        onVersionSelect={(version, content) => {
          // TODO: Request versioned content from server and display
          console.log('[CodeEmbedFullscreen] Version selected:', version);
        }}
      />
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* Code fullscreen container */
  .code-fullscreen-container {
    width: calc(100% - 10px);
    background-color: var(--color-grey-15);
    margin-top: 15px;
    padding-bottom: var(--spacing-8);
    margin-left: var(--spacing-5);
    margin-right: var(--spacing-5);
  }

  /* When preview split is active, container fills available height.
     Uses flex: 1 instead of height: calc() because the parent .content-area
     is itself a flex child (flex: 1) — percentage heights don't resolve
     against flex-sized parents. */
  .code-fullscreen-container.preview-split {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 358px);
    min-height: 0;
    overflow: hidden;
    padding-bottom: 0;
  }

  /* ── Split wrapper — holds code panel + preview panel side by side ── */
  .code-split-wrapper {
    width: 100%;
    flex: 1;
    min-height: 0;
  }

  .code-split-wrapper.split-active {
    display: flex;
    gap: 1px;
    background-color: var(--color-grey-20);
    overflow: hidden;
  }

  /* Desktop: 30/70 horizontal split — code narrow, preview wide */
  .code-panel {
    width: 100%;
    overflow: auto;
  }

  .code-panel.code-panel-split {
    width: 30%;
    flex: 0 0 30%;
    overflow: auto;
    background-color: var(--color-grey-15);
  }

  .preview-panel {
    width: 70%;
    flex: 0 0 70%;
    overflow: hidden;
    background-color: var(--color-grey-15);
    /* position: relative so child can use absolute positioning to fill the panel
       without expanding it to the iframe's content height */
    position: relative;
  }

  /* Mobile: preview only — hide code panel, show full-width preview.
     The user can toggle the preview button off to see code again. */
  @media (max-width: 768px) {
    .code-panel.code-panel-split {
      display: none;
    }

    .preview-panel {
      width: 100%;
      flex: 1 1 auto;
      min-height: 0;
    }
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
    gap: var(--spacing-3);
    padding: 5px 12px;
    border-radius: var(--radius-2);
    border: none;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
    cursor: pointer;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    transition: background-color var(--duration-fast), color var(--duration-fast);
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
    font-size: var(--font-size-xxs);
  }

  /* Per-line container — vertical stack of .code-line rows.
     overflow-x on the container allows horizontal scrolling for long lines
     while keeping line highlighting at the full container width. */
  .code-lines-container {
    width: 100%;
    overflow-x: auto;
    font-size: var(--font-size-small);
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
    padding-right: var(--spacing-6);
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
