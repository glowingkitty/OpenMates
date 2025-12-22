<!--
  frontend/packages/ui/src/components/embeds/web/WebReadEmbedFullscreen.svelte
  
  Fullscreen view for Web Read skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides web read-specific content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results directly
  
  Shows website metadata and full markdown content.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { BaseSkillPreviewData } from '../../../types/appSkills';
  
  // Define result structure based on read_skill.py
  interface WebReadResult {
    type: string;
    url: string;
    title: string;
    markdown: string;
    language?: string;
    favicon?: string;
    og_image?: string;
    og_sitename?: string;
    hash?: string;
  }
  
  interface WebReadPreviewData extends BaseSkillPreviewData {
    results: WebReadResult[];
  }
  
  /**
   * Props for web read embed fullscreen
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Web read results (direct format) */
    results?: WebReadResult[];
    /** Skill preview data (skill preview context) */
    previewData?: WebReadPreviewData;
    /** Close handler */
    onClose: () => void;
  }
  
  let {
    results: resultsProp,
    previewData,
    onClose
  }: Props = $props();
  
  // Extract values from either previewData (skill preview context) or direct props (embed context)
  let results = $derived(previewData?.results || resultsProp || []);
  
  // Get first result for main display
  let firstResult = $derived(results[0]);
  
  function safeHostname(url?: string): string {
    if (!url) return '';
    try {
      return new URL(url).hostname;
    } catch {
      const withoutScheme = url.replace(/^[a-zA-Z]+:\/\//, '');
      return withoutScheme.split('/')[0] || '';
    }
  }
  
  // Format display title
  let displayTitle = $derived(
    firstResult?.title || 
    safeHostname(firstResult?.url) ||
    'Web Read'
  );
  
  // Handle opening website
  function handleOpenWebsite() {
    if (firstResult?.url) {
      window.open(firstResult.url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Render markdown as HTML using markdown-it
  // Store rendered HTML for each result
  let renderedMarkdowns = $state<Map<number, string>>(new Map());
  
  async function renderMarkdown(markdown: string, index: number): Promise<void> {
    if (!markdown) {
      renderedMarkdowns.set(index, '');
      return;
    }
    
    try {
      // Use markdown-it for proper markdown rendering
      const MarkdownIt = (await import('markdown-it')).default;
      const md = new MarkdownIt({
        html: true,
        linkify: true,
        typographer: true,
        breaks: false
      });
      
      // Render markdown to HTML
      const html = md.render(markdown);
      renderedMarkdowns.set(index, html);
    } catch (error) {
      console.error('[WebReadEmbedFullscreen] Error rendering markdown:', error);
      // Fallback: escape HTML and preserve line breaks
      const html = markdown
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
      renderedMarkdowns.set(index, html);
    }
  }
  
  // Render markdown for all results when they change
  $effect(() => {
    results.forEach((result, index) => {
      if (result.markdown && !renderedMarkdowns.has(index)) {
        renderMarkdown(result.markdown, index);
      }
    });
  });
</script>

<UnifiedEmbedFullscreen
  appId="web"
  skillId="read"
  title={displayTitle}
  {onClose}
  onOpen={handleOpenWebsite}
>
  {#snippet headerExtra()}
    {#if results.length > 1}
      <div class="results-indicator">
        <div class="icon_rounded web"></div>
        <span class="results-count">+{results.length - 1} more</span>
      </div>
    {/if}
    
    <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
    <button class="open-button" onclick={handleOpenWebsite}>
      Open Website
    </button>
  {/snippet}
  
  {#snippet content()}
    {#if results.length === 0}
      <div class="no-results">
        <p>No read results available.</p>
      </div>
    {:else}
      {#each results as result, index}
        <div class="read-result">
          <!-- Website metadata section -->
          <div class="metadata-section">
            <div class="metadata-content">
              {#if result.title}
                <div class="website-title">{result.title}</div>
              {/if}
              
              {#if result.url}
                <div class="website-url">
                  <a href={result.url} target="_blank" rel="noopener noreferrer" class="url-link">
                    {result.url}
                  </a>
                </div>
              {/if}
              
              {#if result.og_sitename || result.language}
                <div class="metadata-info">
                  {#if result.og_sitename}
                    <span class="info-item">Site: {result.og_sitename}</span>
                  {/if}
                  {#if result.language}
                    <span class="info-item">Language: {result.language}</span>
                  {/if}
                </div>
              {/if}
            </div>
            
            {#if result.favicon}
              <div class="favicon-container">
                <img 
                  src={result.favicon} 
                  alt="Website favicon"
                  class="favicon"
                  onerror={(e) => { e.currentTarget.style.display = 'none'; }}
                />
              </div>
            {/if}
          </div>
          
          <!-- Markdown content section -->
          {#if result.markdown}
            <div class="markdown-section">
              <div class="markdown-header">
                <h3>Content</h3>
                {#if result.markdown.length}
                  <span class="char-count">{result.markdown.length.toLocaleString()} characters</span>
                {/if}
              </div>
              
              <div class="markdown-content">
                {#if renderedMarkdowns.has(index)}
                  {@html renderedMarkdowns.get(index) || ''}
                {:else if result.markdown}
                  <!-- Loading markdown... -->
                  <p>Loading content...</p>
                {:else}
                  <p>No content available.</p>
                {/if}
              </div>
            </div>
          {:else}
            <div class="no-content">
              <p>No content available for this page.</p>
            </div>
          {/if}
        </div>
        
        {#if index < results.length - 1}
          <hr class="result-divider" />
        {/if}
      {/each}
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .results-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
  }
  
  .results-count {
    font-size: 14px;
    color: var(--color-font-secondary);
  }
  
  .open-button {
    margin-top: 12px;
    padding: 12px 24px;
    background-color: var(--color-primary);
    color: white;
    border: none;
    border-radius: 20px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
  }
  
  .open-button:hover {
    background-color: var(--color-primary-dark);
    transform: translateY(-2px);
  }
  
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
  
  .read-result {
    margin-bottom: 32px;
  }
  
  /* Metadata section */
  .metadata-section {
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
    padding: 16px;
    background-color: var(--color-grey-15);
    border-radius: 12px;
    align-items: flex-start;
  }
  
  .metadata-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .website-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.4;
  }
  
  .website-url {
    font-size: 14px;
    color: var(--color-font-secondary);
  }
  
  .url-link {
    color: var(--color-primary);
    text-decoration: none;
    word-break: break-all;
  }
  
  .url-link:hover {
    text-decoration: underline;
  }
  
  .metadata-info {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 14px;
    color: var(--color-font-tertiary);
  }
  
  .info-item {
    background-color: var(--color-grey-20);
    padding: 4px 12px;
    border-radius: 12px;
  }
  
  .favicon-container {
    flex-shrink: 0;
  }
  
  .favicon {
    width: 32px;
    height: 32px;
    border-radius: 4px;
    object-fit: contain;
  }
  
  /* Markdown section */
  .markdown-section {
    margin-bottom: 24px;
  }
  
  .markdown-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  
  .markdown-header h3 {
    font-size: 20px;
    font-weight: 600;
    color: var(--color-font-primary);
    margin: 0;
  }
  
  .char-count {
    font-size: 14px;
    color: var(--color-font-secondary);
    background-color: var(--color-grey-15);
    padding: 4px 12px;
    border-radius: 12px;
  }
  
  .markdown-content {
    background-color: var(--color-grey-15);
    border-radius: 12px;
    padding: 24px;
    font-size: 15px;
    line-height: 1.7;
    color: var(--color-font-primary);
    word-wrap: break-word;
  }
  
  .markdown-content :global(h1) {
    font-size: 24px;
    font-weight: 600;
    margin: 24px 0 16px 0;
    color: var(--color-font-primary);
  }
  
  .markdown-content :global(h2) {
    font-size: 20px;
    font-weight: 600;
    margin: 20px 0 12px 0;
    color: var(--color-font-primary);
  }
  
  .markdown-content :global(h3) {
    font-size: 18px;
    font-weight: 600;
    margin: 16px 0 10px 0;
    color: var(--color-font-primary);
  }
  
  .markdown-content :global(p) {
    margin: 12px 0;
  }
  
  .markdown-content :global(strong) {
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .markdown-content :global(em) {
    font-style: italic;
  }
  
  .markdown-content :global(a) {
    color: var(--color-primary);
    text-decoration: none;
  }
  
  .markdown-content :global(a:hover) {
    text-decoration: underline;
  }
  
  .markdown-content :global(code) {
    background-color: var(--color-grey-20);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Courier New', monospace;
    font-size: 14px;
  }
  
  .markdown-content :global(pre) {
    background-color: var(--color-grey-20);
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
  }
  
  .markdown-content :global(pre code) {
    background-color: transparent;
    padding: 0;
  }
  
  .no-content {
    padding: 16px;
    background-color: var(--color-grey-15);
    border-radius: 12px;
    text-align: center;
    color: var(--color-font-secondary);
  }
  
  /* Result divider */
  .result-divider {
    border: none;
    border-top: 1px solid var(--color-grey-20);
    margin: 32px 0;
  }
  
  /* Responsive adjustments */
  @media (max-width: 768px) {
    .metadata-section {
      flex-direction: column;
    }
    
    .favicon {
      align-self: flex-start;
    }
  }
</style>
