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
  import hljs from 'highlight.js';
  import DOMPurify from 'dompurify';
  // Import highlight.js theme - using github-dark for dark mode compatibility
  import 'highlight.js/styles/github-dark.css';
  // Import language definitions for syntax highlighting
  import 'highlight.js/lib/languages/javascript';
  import 'highlight.js/lib/languages/typescript';
  import 'highlight.js/lib/languages/python';
  import 'highlight.js/lib/languages/java';
  import 'highlight.js/lib/languages/cpp';
  import 'highlight.js/lib/languages/c';
  import 'highlight.js/lib/languages/rust';
  import 'highlight.js/lib/languages/go';
  import 'highlight.js/lib/languages/ruby';
  import 'highlight.js/lib/languages/php';
  import 'highlight.js/lib/languages/swift';
  import 'highlight.js/lib/languages/kotlin';
  import 'highlight.js/lib/languages/yaml';
  import 'highlight.js/lib/languages/xml';
  import 'highlight.js/lib/languages/markdown';
  import 'highlight.js/lib/languages/bash';
  import 'highlight.js/lib/languages/shell';
  import 'highlight.js/lib/languages/sql';
  import 'highlight.js/lib/languages/json';
  import 'highlight.js/lib/languages/css';
  import 'highlight.js/lib/languages/dockerfile';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from './codeEmbedContent';
  
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
    onFullscreen?: () => void;
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
  
  // Initialize local state from props
  $effect(() => {
    localCodeContent = codeContentProp || '';
    localLanguage = languageProp || '';
    localFilename = filenameProp;
    localLineCount = lineCountProp || 0;
    localStatus = statusProp || 'processing';
    localTaskId = taskIdProp;
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let codeContent = $derived(localCodeContent);
  let language = $derived(localLanguage);
  let filename = $derived(localFilename);
  let lineCount = $derived(localLineCount);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);
  
  // Maximum lines to show in preview
  const MAX_PREVIEW_LINES = 8;
  
  // Reference to the code element for syntax highlighting
  let codeElement: HTMLElement | null = $state(null);

  let parsedContent = $derived.by(() => parseCodeEmbedContent(codeContent, { language, filename }));
  let renderCodeContent = $derived(parsedContent.code);
  let renderLanguage = $derived(parsedContent.language || '');
  let renderFilename = $derived(parsedContent.filename);
  let displayLanguage = $derived.by(() => formatLanguageName(renderLanguage));
  
  // Extract preview lines (max 8 lines)
  let previewLines = $derived.by(() => {
    const content = renderCodeContent;
    if (!content) return [];
    const lines = content.split('\n');
    return lines.slice(0, MAX_PREVIEW_LINES);
  });
  
  // Preview text (joined lines)
  let previewText = $derived(previewLines.join('\n'));
  
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
    return $text('embeds.code_snippet.text');
  });
  
  // Build status text: line count + language (always use code_info.text format)
  let statusText = $derived.by(() => {
    const lineCount = actualLineCount;
    if (lineCount === 0) return '';
    
    // Build line count text with proper singular/plural handling
    const lineCountText = lineCount === 1 
      ? $text('embeds.code_line_singular.text')
      : $text('embeds.code_line_plural.text');
    
    const languageToShow = displayLanguage;
    return languageToShow ? `${lineCount} ${lineCountText}, ${languageToShow}` : `${lineCount} ${lineCountText}`;
  });
  
  // Map skillId to icon name
  const skillIconName = 'coding';
  
  // Apply syntax highlighting after mount and when content changes
  onMount(() => {
    highlightCode(renderCodeContent, renderLanguage, previewText);
  });
  
  // Re-highlight when code content changes
  $effect(() => {
    highlightCode(renderCodeContent, renderLanguage, previewText);
  });
  
  /**
   * Apply syntax highlighting using highlight.js
   * Uses auto-detection if language is not specified
   */
  function highlightCode(content: string, language: string, codeToHighlight: string) {
    if (!codeElement || !content) return;
    if (!codeToHighlight) return;
    
    try {
      let highlighted: string;
      
      if (language && language !== 'text' && language !== 'plaintext') {
        // Try to highlight with specified language
        try {
          highlighted = hljs.highlight(codeToHighlight, { language }).value;
        } catch {
          // Fallback to auto-detection if language not supported
          console.debug(`[CodeEmbedPreview] Language '${language}' not supported, using auto-detection`);
          highlighted = hljs.highlightAuto(codeToHighlight).value;
        }
      } else {
        // Auto-detect language
        highlighted = hljs.highlightAuto(codeToHighlight).value;
      }
      
      // Sanitize the highlighted HTML to prevent XSS
      codeElement.innerHTML = DOMPurify.sanitize(highlighted, {
        ALLOWED_TAGS: ['span'],
        ALLOWED_ATTR: ['class']
      });
    } catch (error) {
      console.warn('[CodeEmbedPreview] Error highlighting code:', error);
      // Fallback to plain text
      codeElement.textContent = codeToHighlight;
    }
  }
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   * This enables real-time updates during streaming without requiring page reload
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: any }) {
    console.debug(`[CodeEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent,
      hasCode: !!data.decodedContent?.code
    });
    
    // Update local state from decoded content
    if (data.decodedContent) {
      // Update code content if available
      if (data.decodedContent.code !== undefined) {
        localCodeContent = data.decodedContent.code || '';
        console.debug(`[CodeEmbedPreview] Updated code content: ${localCodeContent.length} chars`);
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
  }
  
  // Handle stop button click (not applicable for code, but included for consistency)
  async function handleStop() {
    // Code embeds don't have cancellable tasks, but we include this for API consistency
    console.debug('[CodeEmbedPreview] Stop requested (not applicable for code)');
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
	  {#snippet details({ isMobile: isMobileLayout })}
	    <div class="code-details" class:mobile={isMobileLayout}>
	      {#if renderCodeContent}
	        <!-- Code preview with syntax highlighting -->
	        <div class="code-preview-container">
	          <pre class="code-preview"><code bind:this={codeElement}>{previewText}</code></pre>
	        </div>
	      {:else if status === 'processing'}
	        <!-- Processing state -->
	        <div class="processing-placeholder">
          <span class="processing-dot"></span>
          <span class="processing-text">{$text('embeds.processing.text')}</span>
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
  }
  
  .code-preview {
    margin: 0;
    padding: 0;
    font-size: 12px;
    line-height: 1.5;
    overflow: hidden;
    white-space: pre;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    background: transparent;
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
    background: transparent;
    padding: 0;
    margin: 0;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
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
</style>
