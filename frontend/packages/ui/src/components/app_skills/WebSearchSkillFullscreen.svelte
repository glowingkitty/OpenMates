<!--
  frontend/packages/ui/src/components/app_skills/WebSearchSkillFullscreen.svelte
  
  Fullscreen view for Web Search skill results.
  Shows all search results in a scrollable view with images and snippets.
  
  According to web.md architecture:
  - Shows search query and provider
  - "Open on Brave Search" button
  - Horizontal scrollable list of result cards with images
  - Vertical list of result cards with snippets
  - Navigation bars for scrolling
-->

<script lang="ts">
  import AppSkillFullscreenBase from './AppSkillFullscreenBase.svelte';
  import type { WebSearchSkillPreviewData, WebSearchResult } from '../../types/appSkills';
  
  // Props using Svelte 5 runes
  let {
    previewData,
    onClose
  }: {
    previewData: WebSearchSkillPreviewData;
    onClose: () => void;
  } = $props();
  
  // Format the search query with provider name
  let displayTitle = $derived(
    `${previewData.query} via ${previewData.provider}`
  );
  
  // Type assertion for base component prop compatibility
  let previewDataForBase = $derived(previewData as any);
  
  // Get results (should always be present in fullscreen view)
  let results = $derived(previewData.results || []);
  
  // Results with images (for horizontal scroll)
  let imageResults = $derived(
    results.filter(r => r.preview_image_url)
  );
  
  // Results with snippets (for vertical list)
  let snippetResults = $derived(
    results.filter(r => r.snippet)
  );
  
  // Handle opening search in Brave Search
  function handleOpenInProvider() {
    const searchUrl = `https://search.brave.com/search?q=${encodeURIComponent(previewData.query)}`;
    window.open(searchUrl, '_blank', 'noopener,noreferrer');
  }
  
  // Handle result click
  function handleResultClick(result: WebSearchResult) {
    window.open(result.url, '_blank', 'noopener,noreferrer');
  }
  
  // Handle keyboard navigation for result cards
  function handleResultKeydown(e: KeyboardEvent, result: WebSearchResult) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleResultClick(result);
    }
  }
  
  // Handle share action (override base)
  function handleShare() {
    handleOpenInProvider();
  }
</script>

<!-- @ts-ignore - Svelte 5 type inference issue with component props -->
<AppSkillFullscreenBase 
  previewData={previewData as any} 
  title={displayTitle} 
  onClose={onClose} 
  onShare={handleShare}
>
  {#snippet headerExtra()}
    {#if results.length > 0}
      <div class="results-indicator">
        <div class="icon_rounded web"></div>
        <span class="results-count">+{results.length - 1} more</span>
      </div>
    {/if}
    
    <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
    <button class="open-button" onclick={handleOpenInProvider}>
      Open on {previewData.provider}
    </button>
  {/snippet}
  
  {#snippet content({ previewData })}
    {#if results.length === 0}
      <div class="no-results">
        <p>No search results available.</p>
      </div>
    {:else}
      <!-- Horizontal scrollable image results -->
      {#if imageResults.length > 0}
        <div class="image-results-container">
          <div class="image-results-scroll">
            {#each imageResults as result}
              <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
              <div 
                class="image-result-card" 
                role="button"
                tabindex="0"
                onclick={() => handleResultClick(result)}
                onkeydown={(e) => handleResultKeydown(e, result)}
              >
                {#if result.preview_image_url}
                  <img 
                    src={result.preview_image_url} 
                    alt={result.title}
                    class="result-image"
                  />
                {/if}
                <div class="result-title">{result.title}</div>
                {#if result.favicon_url}
                  <div class="result-source">
                    <img src={result.favicon_url} alt="" class="favicon" />
                    <span class="source-url">{new URL(result.url).hostname}</span>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
          <!-- Navigation bar for image results -->
          <div class="nav-bar">
            <button class="nav-button" aria-label="Scroll left">←</button>
            <div class="icon_rounded web"></div>
            <span class="nav-text">Search Completed</span>
            <button class="nav-button" aria-label="Scroll right">→</button>
          </div>
        </div>
      {/if}
      
      <!-- Vertical list of snippet results -->
      {#if snippetResults.length > 0}
        <div class="snippet-results-container">
          {#each snippetResults as result}
            <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
            <div 
              class="snippet-result-card" 
              role="button"
              tabindex="0"
              onclick={() => handleResultClick(result)}
              onkeydown={(e) => handleResultKeydown(e, result)}
            >
              <div class="result-header">
                {#if result.favicon_url}
                  <img src={result.favicon_url} alt="" class="favicon" />
                {:else}
                  <div class="icon_rounded web"></div>
                {/if}
                <div class="result-title">{result.title}</div>
              </div>
              {#if result.snippet}
                <div class="result-snippet">{result.snippet}</div>
              {/if}
              <div class="result-url">{new URL(result.url).hostname}</div>
            </div>
          {/each}
        </div>
        
        <!-- Navigation bar for snippet results -->
        <div class="nav-bar">
          <button class="nav-button" aria-label="Scroll up">←</button>
          <div class="icon_rounded web"></div>
          <span class="nav-text">Search Completed!</span>
          <button class="nav-button" aria-label="Scroll down">→</button>
        </div>
      {/if}
    {/if}
  {/snippet}
</AppSkillFullscreenBase>

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
    background-color: var(--color-error);
    color: white;
    border: none;
    border-radius: 20px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
  }
  
  .open-button:hover {
    background-color: var(--color-error-dark);
    transform: translateY(-2px);
  }
  
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
  
  /* Image results horizontal scroll */
  .image-results-container {
    margin-bottom: 24px;
  }
  
  .image-results-scroll {
    display: flex;
    gap: 16px;
    overflow-x: auto;
    padding-bottom: 8px;
    scrollbar-width: thin;
    scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
  }
  
  .image-results-scroll::-webkit-scrollbar {
    height: 4px;
  }
  
  .image-results-scroll::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .image-results-scroll::-webkit-scrollbar-thumb {
    background-color: rgba(128, 128, 128, 0.2);
    border-radius: 2px;
  }
  
  .image-result-card {
    flex-shrink: 0;
    width: 280px;
    background-color: var(--color-grey-15);
    border-radius: 12px;
    overflow: hidden;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  }
  
  .image-result-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
  }
  
  .result-image {
    width: 100%;
    height: 180px;
    object-fit: cover;
    background-color: var(--color-grey-20);
  }
  
  .image-result-card .result-title {
    padding: 12px;
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .result-source {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px 12px;
  }
  
  .favicon {
    width: 16px;
    height: 16px;
    border-radius: 2px;
  }
  
  .source-url {
    font-size: 12px;
    color: var(--color-font-secondary);
  }
  
  /* Snippet results vertical list */
  .snippet-results-container {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 24px;
  }
  
  .snippet-result-card {
    background-color: var(--color-grey-15);
    border-radius: 12px;
    padding: 16px;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
  }
  
  .snippet-result-card:hover {
    background-color: var(--color-grey-10);
    transform: translateX(4px);
  }
  
  .result-header {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 8px;
  }
  
  .snippet-result-card .result-title {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.4;
    flex: 1;
  }
  
  .result-snippet {
    font-size: 14px;
    color: var(--color-font-secondary);
    line-height: 1.5;
    margin-bottom: 8px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .result-url {
    font-size: 12px;
    color: var(--color-font-tertiary);
  }
  
  /* Navigation bars */
  .nav-bar {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 12px;
    background-color: var(--color-grey-15);
    border-radius: 20px;
    margin-bottom: 16px;
  }
  
  .nav-button {
    background: none;
    border: none;
    color: var(--color-font-secondary);
    font-size: 18px;
    cursor: pointer;
    padding: 4px 8px;
    transition: color 0.2s;
  }
  
  .nav-button:hover {
    color: var(--color-font-primary);
  }
  
  .nav-text {
    font-size: 14px;
    color: var(--color-font-secondary);
  }
</style>

