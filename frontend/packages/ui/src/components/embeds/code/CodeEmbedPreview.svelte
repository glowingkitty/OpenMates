<!--
  frontend/packages/ui/src/components/embeds/CodeEmbedPreview.svelte
  
  Preview component for Code embeds.
  Uses UnifiedEmbedPreview as base and provides code-specific details content.
  
  Details content structure:
  - Processing: "Generating..." placeholder
  - Finished: Syntax-highlighted code preview (max 8 lines)
  - Error: Empty placeholder with code icon
  
  Sizes:
  - Desktop: 300x200px
  - Mobile: 150x290px
-->

<script lang="ts">
  import { onMount } from 'svelte';
  // Import highlight.js themes - github theme for light mode (good contrast), github-dark for dark mode
  // We import github-dark as base (used for dark mode) and override for light mode via CSS below
  import 'highlight.js/styles/github-dark.css';
  // Import shared highlighting utilities (includes all language support + Svelte)
  import { highlightToElement, highlightToLines } from './codeHighlighting';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from './codeEmbedContent';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import { embedPIIStore, addEmbedPIIMappings, removeEmbedPIIMappings } from '../../../stores/embedPIIStore';
  import { loadEmbedPIIMappings } from '../../enter_message/services/codeEmbedService';
  
  /**
   * Props for code embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Programming language */
    language?: string;
    /** Filename */
    filename?: string;
    /** Number of lines in the code */
    lineCount?: number;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
    /** Code content (full code for preview extraction) */
    codeContent?: string;
  }
  
  let {
    id,
    language: languageProp = '',
    filename: filenameProp,
    lineCount: lineCountProp = 0,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen,
    codeContent: codeContentProp = ''
  }: Props = $props();
  
  // Local reactive state for embed data - these can be updated when embed data changes
  // CRITICAL: Using $state allows us to update these values when we receive embed updates
  // via the onEmbedDataUpdated callback from UnifiedEmbedPreview
  // This enables real-time updates during streaming without requiring page reload
  let localCodeContent = $state<string>('');
  let localLanguage = $state<string>('');
  let localFilename = $state<string | undefined>(undefined);
  let localLineCount = $state<number>(0);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  let storeResolved = $state(false);

  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      localCodeContent = codeContentProp || '';
      localLanguage = languageProp || '';
      localFilename = filenameProp;
      localLineCount = lineCountProp || 0;
      localStatus = statusProp || 'processing';
      localTaskId = taskIdProp;
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let codeContent = $derived(localCodeContent);
  let language = $derived(localLanguage);
  let filename = $derived(localFilename);
  let lineCount = $derived(localLineCount);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);
  
  // Maximum lines to show in preview
  // Large variant (400px container): user-visible lines. The per-line gutter rendering
  // (0.8rem/19.2px per line) would fit ~16 lines in 323px usable height; we show 21
  // so the last partial line is visible, confirming there is more content below.
  const MAX_PREVIEW_LINES_STANDARD = 8;
  const MAX_PREVIEW_LINES_LARGE = 21;
  
  // Reference to the code element for syntax highlighting
  let codeElement: HTMLElement | null = $state(null);

  // Subscribe to the global embed PII store to get the current chat's PII state.
  // This allows the preview to reactively apply PII masking without needing
  // to receive props from the parent (previews are mounted imperatively via mount()).
  let embedPIIState = $state({ mappings: [] as import('../../../types/chat').PIIMapping[], revealed: false });
  $effect(() => {
    const unsub = embedPIIStore.subscribe((state) => { embedPIIState = state; });
    return unsub;
  });

  // Load embed-level PII mappings from EmbedStore and register them in the global store.
  // These cover PII that was redacted when the code embed was created (file drop or paste).
  // They are stored separately from the embed content (under embed_pii:{embed_id}, master-key
  // encrypted) so they are never exposed via share links.
  // We clean up on unmount to avoid stale mappings if the embed is removed from view.
  $effect(() => {
    if (!id) return;
    let cancelled = false;
    loadEmbedPIIMappings(id).then((mappings) => {
      if (cancelled) return;
      if (mappings.length > 0) {
        addEmbedPIIMappings(id, mappings);
      }
    });
    return () => {
      cancelled = true;
      removeEmbedPIIMappings(id);
    };
  });

  /**
   * Apply PII masking to the raw code string before parsing/displaying in preview.
   * Mirrors the same logic in CodeEmbedFullscreen.
   */
  let piiProcessedCodeContent = $derived.by(() => {
    const { mappings, revealed } = embedPIIState;
    if (!mappings.length || !codeContent) return codeContent;
    if (revealed) {
      return restorePIIInText(codeContent, mappings);
    } else {
      return replacePIIOriginalsWithPlaceholders(codeContent, mappings);
    }
  });

  // Parse code content to extract language, filename, and actual code
  let parsedContent = $derived.by(() => parseCodeEmbedContent(piiProcessedCodeContent, { language, filename }));
  let renderCodeContent = $derived(parsedContent.code);
  let renderLanguage = $derived(parsedContent.language || '');
  let renderFilename = $derived(parsedContent.filename);
  let displayLanguage = $derived.by(() => formatLanguageName(renderLanguage));
  
  // isLargePreview is set reactively from the snippet param (isLarge).
  // This drives previewLines and syntax highlighting to use more lines
  // when the embed is rendered in the expanded (400px) large container.
  let isLargePreview = $state(false);

  let previewLines = $derived.by(() => {
    const c = renderCodeContent;
    if (!c) return [];
    const lines = c.split('\n');
    const maxLines = isLargePreview ? MAX_PREVIEW_LINES_LARGE : MAX_PREVIEW_LINES_STANDARD;
    return lines.slice(0, maxLines);
  });
  
  let previewText = $derived(previewLines.join('\n'));

  // Per-line highlighted HTML for the large variant (mirrors CodeEmbedFullscreen structure).
  // Only computed when isLargePreview to avoid unnecessary work in the small variant.
  let largeHighlightedLines = $derived.by(() => {
    if (!isLargePreview || !renderCodeContent) return [];
    return highlightToLines(previewText, renderLanguage);
  });
  
  // Calculate actual line count from content if not provided
  let actualLineCount = $derived.by(() => {
    if (lineCount > 0) return lineCount;
    return countCodeLines(renderCodeContent);
  });
  
  // Build skill name for BasicInfosBar: filename (or "Code snippet") on first line
  // Second line will be handled by showStatus (line count + language)
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
  
  // Build status text: line count + language (always use code_info.text format).
  // When line count is not yet available (embed data still loading from EmbedStore),
  // fall back to just the display language so "Completed" is never shown.
  let statusText = $derived.by(() => {
    const lineCount = actualLineCount;
    const languageToShow = displayLanguage;

    if (lineCount > 0) {
      // Full info: "42 lines, Python"
      const lineCountText = lineCount === 1
        ? $text('embeds.code_line_singular')
        : $text('embeds.code_line_plural');
      return languageToShow
        ? `${lineCount} ${lineCountText}, ${languageToShow}`
        : `${lineCount} ${lineCountText}`;
    }

    // Line count not available yet — show language only so we never fall back to "Completed"
    if (languageToShow) return languageToShow;

    // Last resort: return a single space so BasicInfosBar uses customStatusText
    // (a non-empty customStatusText suppresses the default "Completed" fallback)
    return ' ';
  });
  
  // Map skillId to icon name
  const skillIconName = 'coding';
  
  // Apply syntax highlighting for the small variant (uses highlightToElement on a <code> element).
  // Large variant uses highlightToLines (reactive derived) — no manual DOM update needed.
  onMount(() => {
    if (!isLargePreview) highlightToElement(codeElement, previewText, renderLanguage);
  });
  
  // Re-highlight small variant when code content changes
  $effect(() => {
    if (!isLargePreview) highlightToElement(codeElement, previewText, renderLanguage);
  });
  
  /**
   * Decoded content structure from embed data updates
   * Contains the parsed code embed data from the server
   */
  interface DecodedCodeContent {
    code?: string;
    language?: string;
    filename?: string;
    lineCount?: number;
    task_id?: string;
  }

  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   * This enables real-time updates during streaming without requiring page reload
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: DecodedCodeContent | null }) {
    // Update local state from decoded content
    if (data.decodedContent) {
      // Update code content if available
      if (data.decodedContent.code !== undefined) {
        localCodeContent = data.decodedContent.code || '';
      }
      
      // Update language if available
      if (data.decodedContent.language !== undefined) {
        localLanguage = data.decodedContent.language || '';
      }
      
      // Update filename if available
      if (data.decodedContent.filename !== undefined) {
        localFilename = data.decodedContent.filename;
      }
      
      // Update line count if available
      if (data.decodedContent.lineCount !== undefined) {
        localLineCount = data.decodedContent.lineCount || 0;
      }
      
      // Update task ID if available
      if (data.decodedContent.task_id !== undefined) {
        localTaskId = data.decodedContent.task_id;
      }
    }
    
    // Update status
    if (data.status) {
      localStatus = data.status as 'processing' | 'finished' | 'error';
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }
  }
  
  // Handle stop button click (not applicable for code, but included for consistency)
  async function handleStop() {
    // Code embeds don't have cancellable tasks, but we include this for API consistency
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="code"
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
	  {#snippet details({ isMobile: isMobileLayout, isLarge: isLargeLayout })}
	    {(isLargePreview = isLargeLayout, undefined)}
	    <div class="code-details" class:mobile={isMobileLayout}>
	      {#if renderCodeContent}
	        <!-- Code preview with syntax highlighting -->
	        <div class="code-preview-container">
	          {#if isLargePreview}
	            <!-- Large variant: per-line gutter rendering matching CodeEmbedFullscreen -->
	            <div class="preview-lines-container">
	              {#each largeHighlightedLines as lineHtml, i}
	                <div class="preview-line">
	                  <span class="preview-line-gutter" aria-hidden="true">{i + 1}</span>
	                  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
	                  <code class="preview-line-text">{@html lineHtml}</code>
	                </div>
	              {/each}
	            </div>
	          {:else}
	            <!-- Small variant: single highlighted block -->
	            <pre class="code-preview"><code bind:this={codeElement}>{previewText}</code></pre>
	          {/if}
	        </div>
	      {:else if status === 'processing'}
	        <!-- Processing state -->
	        <div class="processing-placeholder">
          <span class="processing-dot"></span>
          <span class="processing-text">{$text('embeds.processing')}</span>
        </div>
      {:else}
        <!-- Error/empty state -->
        <div class="empty-placeholder">
          <div class="code-icon" data-skill-icon="coding"></div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Code Details Content
     =========================================== */
  
  .code-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    /* Ensure no background shows through during 3D transforms */
    background: transparent;
  }
  
  /* Desktop layout: vertically centered content */
  .code-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .code-details.mobile {
    justify-content: flex-start;
  }
  
  /* Code preview container */
  .code-preview-container {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    /* Ensure no background shows through during 3D transforms */
    background: transparent;
  }
  
  .code-preview {
    margin: 0;
    /* Top padding gives first line breathing room from the card edge */
    padding: 0.75rem 0 0 0;
    font-size: 0.75rem;
    line-height: 1.5;
    overflow: hidden;
    white-space: pre;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    /* Force transparent background - override any inherited styles */
    background: transparent !important;
    color: var(--color-font-primary);
    width: 100%;
    height: 100%;
    display: block;
    flex: 1;
    min-height: 0;
  }
  
  .code-details.mobile .code-preview {
    font-size: 11px;
    line-height: 1.4;
  }
  
  .code-preview code {
    display: block;
    color: var(--color-font-primary);
    background: transparent !important;
    padding: 0;
    margin: 0;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
  }
  
  /* Override highlight.js theme backgrounds - embeds use parent background */
  .code-preview code:global(.hljs) {
    background: transparent !important;
  }
  
  /* Syntax highlighting colors - basic support */
  .code-preview code :global(.keyword) {
    color: var(--color-syntax-keyword, #c678dd);
  }
  
  .code-preview code :global(.string) {
    color: var(--color-syntax-string, #98c379);
  }
  
  .code-preview code :global(.comment) {
    color: var(--color-syntax-comment, #5c6370);
  }
  
  .code-preview code :global(.function) {
    color: var(--color-syntax-function, #61afef);
  }
  
  .code-preview code :global(.number) {
    color: var(--color-syntax-number, #d19a66);
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
  
  .empty-placeholder .code-icon {
    width: 48px;
    height: 48px;
    opacity: 0.3;
    background-color: var(--color-font-tertiary);
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
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
  
  /* Code skill icon - this is skill-specific and belongs here, not in UnifiedEmbedPreview */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="coding"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="coding"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
  }

  /* ===========================================
     Light Mode Contrast Fix for Syntax Highlighting
     highlight.js github-dark theme has hardcoded dark background colors
     which show poor contrast in light mode (light card background + dark theme colors).
     We override the hljs token colors for light mode using github light theme colors.
     =========================================== */

  /* Light mode: use github light theme colors for good contrast on light backgrounds */
  :global([data-theme="light"] .unified-embed-preview .hljs-doctag),
  :global([data-theme="light"] .unified-embed-preview .hljs-keyword),
  :global([data-theme="light"] .unified-embed-preview .hljs-meta .hljs-keyword),
  :global([data-theme="light"] .unified-embed-preview .hljs-template-tag),
  :global([data-theme="light"] .unified-embed-preview .hljs-template-variable),
  :global([data-theme="light"] .unified-embed-preview .hljs-type),
  :global([data-theme="light"] .unified-embed-preview .hljs-variable\.language_) {
    /* github light: prettylights-syntax-keyword */
    color: #d73a49; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-title),
  :global([data-theme="light"] .unified-embed-preview .hljs-title\.class_),
  :global([data-theme="light"] .unified-embed-preview .hljs-title\.function_) {
    /* github light: prettylights-syntax-entity */
    color: #6f42c1; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-attr),
  :global([data-theme="light"] .unified-embed-preview .hljs-attribute),
  :global([data-theme="light"] .unified-embed-preview .hljs-literal),
  :global([data-theme="light"] .unified-embed-preview .hljs-number),
  :global([data-theme="light"] .unified-embed-preview .hljs-operator),
  :global([data-theme="light"] .unified-embed-preview .hljs-variable),
  :global([data-theme="light"] .unified-embed-preview .hljs-selector-attr),
  :global([data-theme="light"] .unified-embed-preview .hljs-selector-class),
  :global([data-theme="light"] .unified-embed-preview .hljs-selector-id) {
    /* github light: prettylights-syntax-constant */
    color: #005cc5; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-regexp),
  :global([data-theme="light"] .unified-embed-preview .hljs-string),
  :global([data-theme="light"] .unified-embed-preview .hljs-meta .hljs-string) {
    /* github light: prettylights-syntax-string */
    color: #032f62; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-built_in),
  :global([data-theme="light"] .unified-embed-preview .hljs-symbol) {
    /* github light: prettylights-syntax-variable */
    color: #e36209; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-comment),
  :global([data-theme="light"] .unified-embed-preview .hljs-code),
  :global([data-theme="light"] .unified-embed-preview .hljs-formula) {
    /* github light: prettylights-syntax-comment */
    color: #6a737d; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-name),
  :global([data-theme="light"] .unified-embed-preview .hljs-bullet),
  :global([data-theme="light"] .unified-embed-preview .hljs-deletion) {
    /* github light: prettylights-syntax-markup */
    color: #b31d28; /* intentional: syntax highlight color, must be hardcoded */
  }

  :global([data-theme="light"] .unified-embed-preview .hljs-section),
  :global([data-theme="light"] .unified-embed-preview .hljs-link) {
    color: #0366d6; /* intentional: syntax highlight color, must be hardcoded */
  }

  /* In light mode the base hljs text should be dark for readability */
  :global([data-theme="light"] .unified-embed-preview code.hljs) {
    color: #24292e; /* intentional: github light base text color, must be hardcoded */
  }

  /* Large preview: use 0.8rem (≈12.8px) so more lines fit in the 400px container. */
  @container embed-preview (min-width: 401px) {
    .code-preview {
      font-size: 0.8rem;
      padding-top: 1rem;
    }
  }

  /* ===========================================
     Large preview: per-line gutter rendering
     Mirrors CodeEmbedFullscreen .code-lines-container structure.
     =========================================== */

  /* Container for all preview lines — overflow hidden to clip at card edge */
  .preview-lines-container {
    width: 100%;
    overflow: hidden;
    font-size: 0.8rem;
    line-height: 1.5;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    padding-top: 1rem;
  }

  /* Each line: gutter number on left, code text on right */
  .preview-line {
    display: flex;
    align-items: baseline;
    white-space: pre;
  }

  /* Gutter: right-aligned line numbers, not selectable, dimmed */
  .preview-line-gutter {
    flex: 0 0 auto;
    min-width: 32px;
    padding-right: 10px;
    text-align: right;
    color: var(--color-font-tertiary);
    user-select: none;
    -webkit-user-select: none;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
  }

  /* Code text: no wrapping, inherits font */
  .preview-line-text {
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
  }
</style>
