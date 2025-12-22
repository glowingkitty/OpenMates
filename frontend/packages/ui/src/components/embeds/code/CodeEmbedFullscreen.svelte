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
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import BasicInfosBar from '../BasicInfosBar.svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { downloadCodeFile } from '../../../services/zipExportService';
  import { notificationStore } from '../../../stores/notificationStore';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from './codeEmbedContent';
  
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
  }
  
  let {
    language = '',
    filename,
    lineCount = 0,
    codeContent,
    onClose
  }: Props = $props();
  
  // Reference to the code element for syntax highlighting
  let codeElement: HTMLElement | null = $state(null);

  let parsedContent = $derived.by(() => parseCodeEmbedContent(codeContent, { language, filename }));
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
    return $text('embeds.code_snippet.text');
  });
  
  // No header in fullscreen for code embeds (buttons overlay the top area)
  const fullscreenTitle = '';
  
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
    highlightCode(renderCodeContent, renderLanguage);
  });
  
  // Re-highlight when code content changes
  $effect(() => {
    highlightCode(renderCodeContent, renderLanguage);
  });
  
  /**
   * Apply syntax highlighting using highlight.js
   * Uses auto-detection if language is not specified
   */
  function highlightCode(content: string, language: string) {
    if (!codeElement || !content) return;
    
    try {
      let highlighted: string;
      
      if (language && language !== 'text' && language !== 'plaintext') {
        // Try to highlight with specified language
        try {
          highlighted = hljs.highlight(content, { language }).value;
        } catch {
          // Fallback to auto-detection if language not supported
          console.debug(`[CodeEmbedFullscreen] Language '${language}' not supported, using auto-detection`);
          highlighted = hljs.highlightAuto(content).value;
        }
      } else {
        // Auto-detect language
        highlighted = hljs.highlightAuto(content).value;
      }
      
      // Sanitize the highlighted HTML to prevent XSS
      codeElement.innerHTML = DOMPurify.sanitize(highlighted, {
        ALLOWED_TAGS: ['span'],
        ALLOWED_ATTR: ['class']
      });
    } catch (error) {
      console.warn('[CodeEmbedFullscreen] Error highlighting code:', error);
      // Fallback to plain text
      codeElement.textContent = renderCodeContent;
    }
  }
  
  // Handle copy code to clipboard
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
  
  // Determine if mobile layout
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );
</script>

<UnifiedEmbedFullscreen
  appId="code"
  skillId="code"
  title={fullscreenTitle}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
>
  {#snippet content()}
    {#if renderCodeContent}
      <!-- Full code with syntax highlighting -->
      <div class="code-fullscreen-container">
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
  
  {#snippet bottomBar()}
    <div class="bottom-bar-wrapper">
      <BasicInfosBar
        appId="code"
        skillId="code"
        {skillIconName}
        status="finished"
        {skillName}
        showStatus={true}
        customStatusText={statusText}
        showSkillIcon={false}
        {isMobile}
      />
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* Code fullscreen container */
  .code-fullscreen-container {
    width: 100%;
    background-color: var(--color-grey-15);
    border-radius: 12px;
    padding: 16px;
    margin-top: 40px;
    overflow: hidden;
    margin-bottom: 16px;
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
    font-size: 16px;
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
    font-size: 16px;
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
