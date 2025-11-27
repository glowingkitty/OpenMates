<!--
  frontend/packages/ui/src/components/embeds/VideosSearchEmbedFullscreen.svelte
  
  Fullscreen view for Videos Search skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides skill-specific content.
  
  Shows:
  - Search query and provider
  - Video embeds in a grid (3 per row on desktop, stacked on mobile)
  - Each video uses WebsiteEmbedPreview component (300x200px)
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
   * Video search result interface
   */
  interface VideoSearchResult {
    title?: string;
    url: string;
    thumbnail?: {
      src?: string;
      original?: string;
    };
    meta_url?: {
      favicon?: string;
    };
    description?: string;
    snippet?: string;
  }
  
  /**
   * Props for videos search embed fullscreen
   */
  interface Props {
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave Search') */
    provider: string;
    /** Search results */
    results?: VideoSearchResult[];
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
      console.debug('[VideosSearchEmbedFullscreen] Copied YAML to clipboard');
    } catch (error) {
      console.error('[VideosSearchEmbedFullscreen] Failed to copy YAML:', error);
    }
  }
  
  // Handle video fullscreen (from WebsiteEmbedPreview)
  function handleVideoFullscreen(videoData: any) {
    // For now, just open the video in a new tab
    // In the future, we could show a video player fullscreen view
    if (videoData.url) {
      window.open(videoData.url, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="videos"
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
      <!-- Video embeds grid -->
      <div class="video-embeds-grid" class:mobile={isMobile}>
        {#each results as result, index}
          {@const thumbnailUrl = result.thumbnail?.original || result.thumbnail?.src}
          {@const faviconUrl = result.meta_url?.favicon}
          {@const description = result.description || result.snippet}
          <WebsiteEmbedPreview
            id={`video-${index}`}
            url={result.url}
            title={result.title}
            description={description}
            favicon={faviconUrl}
            image={thumbnailUrl}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleVideoFullscreen({
              url: result.url,
              title: result.title,
              description: description,
              favicon: faviconUrl,
              image: thumbnailUrl
            })}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
  
  {#snippet bottomBar()}
    <div class="bottom-bar-wrapper">
      <BasicInfosBar
        appId="videos"
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
  
  /* Video embeds grid - responsive with auto-fill */
  .video-embeds-grid {
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
  .video-embeds-grid.mobile {
    grid-template-columns: 1fr;
  }
  
  /* Ensure each embed maintains proper size */
  .video-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>

