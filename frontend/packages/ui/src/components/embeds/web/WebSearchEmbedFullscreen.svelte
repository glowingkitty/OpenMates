<!--
  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
  
  Fullscreen view for Web Search skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides skill-specific content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives query, provider, results directly
  
  Shows:
  - Search query and provider
  - Website embeds in a grid (3 per row on desktop, stacked on mobile)
  - Each website uses WebsiteEmbedPreview component (300x200px)
  - Basic infos bar at the bottom
  - Top bar with open, copy, and minimize buttons
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import WebsiteEmbedPreview from './WebsiteEmbedPreview.svelte';
  import BasicInfosBar from '../BasicInfosBar.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import type { WebSearchSkillPreviewData } from '../../../types/appSkills';
  
  /**
   * Web search result interface
   */
  interface WebSearchResult {
    title?: string;
    url: string;
    favicon_url?: string;
    preview_image_url?: string;
    snippet?: string;
  }
  
  /**
   * Props for web search embed fullscreen
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Search query (direct format) */
    query?: string;
    /** Search provider (e.g., 'Brave Search') (direct format) */
    provider?: string;
    /** Search results (direct format) */
    results?: WebSearchResult[];
    /** Skill preview data (skill preview context) */
    previewData?: WebSearchSkillPreviewData;
    /** Close handler */
    onClose: () => void;
  }
  
  let {
    query: queryProp,
    provider: providerProp,
    results: resultsProp,
    previewData,
    onClose
  }: Props = $props();
  
  // Extract values from either previewData (skill preview context) or direct props (embed context)
  let query = $derived(previewData?.query || queryProp || '');
  let provider = $derived(previewData?.provider || providerProp || 'Brave Search');
  let results = $derived(previewData?.results || resultsProp || []);
  
  // Determine if mobile layout
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );
  
  // Format the search query with provider name for title
  let displayTitle = $derived(`${query} via ${provider}`);
  
  // Handle opening search in provider
  function handleOpenInProvider() {
    const searchUrl = `https://search.brave.com/search?q=${encodeURIComponent(query)}`;
    window.open(searchUrl, '_blank', 'noopener,noreferrer');
  }
  
  // Handle copy YAML of search results
  async function handleCopyYAML() {
    try {
      const yamlData = {
        query: query,
        provider: provider,
        results: results.map(r => ({
          title: r.title,
          url: r.url,
          snippet: r.snippet
        }))
      };
      
      // Convert to YAML format
      let yaml = `query: "${query}"\n`;
      yaml += `provider: "${provider}"\n`;
      yaml += `results:\n`;
      
      results.forEach((result, index) => {
        yaml += `  - title: "${result.title || ''}"\n`;
        yaml += `    url: "${result.url}"\n`;
        if (result.snippet) {
          yaml += `    snippet: "${result.snippet.replace(/"/g, '\\"')}"\n`;
        }
      });
      
      await navigator.clipboard.writeText(yaml);
      console.debug('[WebSearchEmbedFullscreen] Copied YAML to clipboard');
    } catch (error) {
      console.error('[WebSearchEmbedFullscreen] Failed to copy YAML:', error);
    }
  }
  
  // Handle website fullscreen (from WebsiteEmbedPreview)
  function handleWebsiteFullscreen(websiteData: any) {
    // For now, just open the website in a new tab
    // In the future, we could show a website fullscreen view
    if (websiteData.url) {
      window.open(websiteData.url, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="web"
  skillId="search"
  title={displayTitle}
  {onClose}
  onOpen={handleOpenInProvider}
  onCopy={handleCopyYAML}
>
  {#snippet content()}
    {#if results.length === 0}
      <div class="no-results">
        <p>No search results available.</p>
      </div>
    {:else}
      <!-- Website embeds grid -->
      <div class="website-embeds-grid" class:mobile={isMobile}>
        {#each results as result, index}
          <WebsiteEmbedPreview
            id={`website-${index}`}
            url={result.url}
            title={result.title}
            description={result.snippet}
            favicon={result.favicon_url}
            image={result.preview_image_url}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleWebsiteFullscreen({
              url: result.url,
              title: result.title,
              description: result.snippet,
              favicon: result.favicon_url,
              image: result.preview_image_url
            })}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
  
  {#snippet bottomBar()}
    <div class="bottom-bar-wrapper">
      <BasicInfosBar
        appId="web"
        skillId="search"
        skillIconName="search"
        status="finished"
        skillName={query}
        showStatus={false}
        isMobile={isMobile}
      />
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* No results message */
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
  
  /* Website embeds grid - responsive with auto-fill */
  .website-embeds-grid {
    display: grid;
    gap: 16px;
    width: 100%;
    max-width: 1000px;
    margin: 0 auto;
    padding-bottom: 100px; /* Space for bottom bar + gradient */
    /* Responsive: auto-fit columns with minimum 280px width */
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }
  
  /* Mobile: single column (stacked) */
  .website-embeds-grid.mobile {
    grid-template-columns: 1fr;
  }
  
  /* Ensure each embed maintains proper size */
  .website-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>

