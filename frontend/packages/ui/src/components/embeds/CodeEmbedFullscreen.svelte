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
  import UnifiedEmbedFullscreen from './UnifiedEmbedFullscreen.svelte';
  import BasicInfosBar from './BasicInfosBar.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
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
  
  // Display language name (capitalize first letter)
  let displayLanguage = $derived(
    language ? language.charAt(0).toUpperCase() + language.slice(1) : ''
  );
  
  // Calculate actual line count from content if not provided
  let actualLineCount = $derived(() => {
    if (lineCount > 0) return lineCount;
    if (!codeContent) return 0;
    return codeContent.split('\n').length;
  });
  
  // Build skill name for BasicInfosBar: filename (or "Code snippet")
  let skillName = $derived.by(() => {
    // Use filename if provided, otherwise use translation
    if (filename) {
      return filename;
    }
    // Otherwise use translation for "Code snippet"
    return $text('embeds.code_snippet.text');
  });
  
  // Build fullscreen title: same as skill name
  let fullscreenTitle = $derived(skillName);
  
  // Build status text: line count + language (only if language is known)
  let statusText = $derived.by(() => {
    const lineCount = actualLineCount();
    if (lineCount === 0) return '';
    
    // Build line count text with plural handling
    const lineCountText = $text('embeds.code_lines.text', { count: lineCount });
    
    // Add language only if known
    if (language && language !== 'text' && language !== 'plaintext') {
      return $text('embeds.code_info.text', {
        lineCount: lineCountText,
        language: displayLanguage
      });
    }
    
    return lineCountText;
  });
  
  // Map skillId to icon name
  const skillIconName = 'coding';
  
  // Apply syntax highlighting after mount and when content changes
  onMount(() => {
    highlightCode();
  });
  
  // Re-highlight when code content changes
  $effect(() => {
    // Track dependencies
    const _ = codeContent;
    const __ = language;
    highlightCode();
  });
  
  /**
   * Apply syntax highlighting using highlight.js
   * Uses auto-detection if language is not specified
   */
  function highlightCode() {
    if (!codeElement || !codeContent) return;
    
    try {
      let highlighted: string;
      
      if (language && language !== 'text' && language !== 'plaintext') {
        // Try to highlight with specified language
        try {
          highlighted = hljs.highlight(codeContent, { language }).value;
        } catch (e) {
          // Fallback to auto-detection if language not supported
          console.debug(`[CodeEmbedFullscreen] Language '${language}' not supported, using auto-detection`);
          highlighted = hljs.highlightAuto(codeContent).value;
        }
      } else {
        // Auto-detect language
        highlighted = hljs.highlightAuto(codeContent).value;
      }
      
      // Sanitize the highlighted HTML to prevent XSS
      codeElement.innerHTML = DOMPurify.sanitize(highlighted, {
        ALLOWED_TAGS: ['span'],
        ALLOWED_ATTR: ['class']
      });
    } catch (error) {
      console.warn('[CodeEmbedFullscreen] Error highlighting code:', error);
      // Fallback to plain text
      codeElement.textContent = codeContent;
    }
  }
  
  // Handle copy code to clipboard
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(codeContent);
      console.debug('[CodeEmbedFullscreen] Copied code to clipboard');
      // TODO: Show toast notification
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to copy code:', error);
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
>
  {#snippet content()}
    {#if codeContent}
      <!-- Full code with syntax highlighting -->
      <div class="code-fullscreen-container">
        <pre class="code-fullscreen"><code bind:this={codeElement}>{codeContent}</code></pre>
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
    overflow-x: auto;
    margin-bottom: 16px;
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
    width: 100%;
    display: block;
    overflow-x: auto;
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

