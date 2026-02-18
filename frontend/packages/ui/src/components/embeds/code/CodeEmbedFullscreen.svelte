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
  import { highlightToElement } from './codeHighlighting';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { downloadCodeFile } from '../../../services/zipExportService';
  import { notificationStore } from '../../../stores/notificationStore';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from './codeEmbedContent';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import type { PIIMapping } from '../../../types/chat';
  
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
    showChatButton = false,
    onShowChat,
    piiMappings = [],
    piiRevealed = false
  }: Props = $props();

  // Local PII reveal toggle — initialised from prop but user can flip it in fullscreen.
  let localPiiRevealed = $state(piiRevealed);

  // Keep localPiiRevealed in sync when the parent prop changes.
  $effect(() => {
    localPiiRevealed = piiRevealed;
  });

  /** Whether there are any PII mappings to apply (controls button visibility) */
  let hasPII = $derived(piiMappings.length > 0);

  function togglePII() {
    localPiiRevealed = !localPiiRevealed;
  }
  
  // Reference to the code element for syntax highlighting
  let codeElement: HTMLElement | null = $state(null);

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
  
  // No header in fullscreen for code embeds (buttons overlay the top area)
  const fullscreenTitle = '';
  
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
  
  // Apply syntax highlighting after mount and when content changes
  onMount(() => {
    highlightToElement(codeElement, renderCodeContent, renderLanguage);
  });
  
  // Re-highlight when code content changes
  $effect(() => {
    highlightToElement(codeElement, renderCodeContent, renderLanguage);
  });
  
  // Handle copy code to clipboard.
  // Copies the PII-processed content (original values if revealed, placeholders if hidden).
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(renderCodeContent);
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
  title={fullscreenTitle}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
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
        <div class="code-fullscreen-grid">
          <pre class="line-numbers" aria-hidden="true">{Array.from({ length: actualLineCount }, (_, i) => i + 1).join('\n')}</pre>
          <pre class="code-fullscreen"><code bind:this={codeElement}>{renderCodeContent}</code></pre>
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

  .code-fullscreen-grid {
    display: flex;
    align-items: flex-start;
    width: 100%;
    gap: 0;
  }

  .line-numbers {
    margin: 0;
    padding: 0 12px 0 0;
    font-size: 14px;
    line-height: 1.6;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    color: var(--color-font-tertiary);
    text-align: right;
    user-select: none;
    -webkit-user-select: none;
    flex: 0 0 auto;
  }
  
  .code-fullscreen {
    margin: 0;
    padding: 0;
    font-size: 14px;
    line-height: 1.6;
    white-space: pre;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    background: transparent;
    color: var(--color-font-primary);
    display: block;
    overflow-x: auto;
    width: 100%;
    min-width: 0;
    user-select: text;
    -webkit-user-select: text;
  }
  
  .code-fullscreen code {
    display: block;
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
  
  /* Syntax highlighting colors - basic support */
  .code-fullscreen code :global(.keyword) {
    color: var(--color-syntax-keyword, #c678dd);
  }
  
  .code-fullscreen code :global(.string) {
    color: var(--color-syntax-string, #98c379);
  }
  
  .code-fullscreen code :global(.comment) {
    color: var(--color-syntax-comment, #5c6370);
  }
  
  .code-fullscreen code :global(.function) {
    color: var(--color-syntax-function, #61afef);
  }
  
  .code-fullscreen code :global(.number) {
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
