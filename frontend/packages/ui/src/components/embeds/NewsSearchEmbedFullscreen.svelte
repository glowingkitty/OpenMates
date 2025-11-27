<!--
  frontend/packages/ui/src/components/embeds/NewsSearchEmbedFullscreen.svelte
  
  Fullscreen view for News Search skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides skill-specific content.
  
  Shows:
  - Search query and provider
  - News article embeds in a grid (3 per row on desktop, stacked on mobile)
  - Each article uses WebsiteEmbedPreview component (300x200px)
  - Basic infos bar at the bottom
  - Top bar with open, copy, and minimize buttons
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from './UnifiedEmbedFullscreen.svelte';
  import WebsiteEmbedPreview from './WebsiteEmbedPreview.svelte';
  import BasicInfosBar from './BasicInfosBar.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * News search result interface
   */
  interface NewsSearchResult {
    title?: string;
    url: string;
    favicon_url?: string;
    meta_url?: {
      favicon?: string;
    };
    thumbnail?: {
      original?: string;
    };
    description?: string;
    snippet?: string;
  }
  
  /**
   * Props for news search embed fullscreen
   */
  interface Props {
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave Search') */
    provider: string;
    /** Search results */
    results?: NewsSearchResult[];
    /** Close handler */
    onClose: () => void;
  }
  
  let {
    query,
    provider,
    results = [],
    onClose
  }: Props = $props();
  
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
          description: r.description || r.snippet
        }))
      };
      
      // Convert to YAML format
      let yaml = `query: "${query}"\n`;
      yaml += `provider: "${provider}"\n`;
      yaml += `results:\n`;
      
      results.forEach((result) => {
        yaml += `  - title: "${result.title || ''}"\n`;
        yaml += `    url: "${result.url}"\n`;
        const desc = result.description || result.snippet;
        if (desc) {
          yaml += `    description: "${desc.replace(/"/g, '\\"')}"\n`;
        }
      });
      
      await navigator.clipboard.writeText(yaml);
      console.debug('[NewsSearchEmbedFullscreen] Copied YAML to clipboard');
    } catch (error) {
      console.error('[NewsSearchEmbedFullscreen] Failed to copy YAML:', error);
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
  appId="news"
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
      <!-- News article embeds grid -->
      <div class="article-embeds-grid" class:mobile={isMobile}>
        {#each results as result, index}
          {@const faviconUrl = result.meta_url?.favicon || result.favicon_url}
          {@const imageUrl = result.thumbnail?.original}
          {@const description = result.description || result.snippet}
          <WebsiteEmbedPreview
            id={`news-article-${index}`}
            url={result.url}
            title={result.title}
            description={description}
            favicon={faviconUrl}
            image={imageUrl}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleWebsiteFullscreen({
              url: result.url,
              title: result.title,
              description: description,
              favicon: faviconUrl,
              image: imageUrl
            })}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
  
  {#snippet bottomBar()}
    <div class="bottom-bar-wrapper">
      <BasicInfosBar
        appId="news"
        skillId="search"
        skillIconName="search"
        status="finished"
        skillName={query}
        showStatus={false}
        {isMobile}
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
  
  /* Article embeds grid - responsive with auto-fill */
  .article-embeds-grid {
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
  .article-embeds-grid.mobile {
    grid-template-columns: 1fr;
  }
  
  /* Ensure each embed maintains proper size */
  .article-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>

