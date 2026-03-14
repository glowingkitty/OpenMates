<!--
  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
  
  Fullscreen view for Web Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.
  
  Shows:
  - Header with search query and "via {provider}" formatting
  - Website embeds in a responsive grid (YouTube URLs render as video embeds)
  - Overlay drill-down into WebsiteEmbedFullscreen or VideoEmbedFullscreen
  
  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.
  
  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from "../SearchResultsTemplate.svelte";
  import WebsiteEmbedPreview from "./WebsiteEmbedPreview.svelte";
  import WebsiteEmbedFullscreen from "./WebsiteEmbedFullscreen.svelte";
  import VideoEmbedPreview from "../videos/VideoEmbedPreview.svelte";
  import VideoEmbedFullscreen from "../videos/VideoEmbedFullscreen.svelte";
  import { text } from "@repo/ui";

  // YouTube URL detection pattern — matches youtube.com and youtu.be variants
  const YOUTUBE_URL_RE =
    /^https?:\/\/(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)/i;

  /**
   * Check if a URL is a YouTube video URL
   */
  function isYouTubeUrl(url: string | undefined): boolean {
    return !!url && YOUTUBE_URL_RE.test(url);
  }

  /**
   * Web search result interface (transformed from child embeds).
   * Results with YouTube URLs are flagged as isVideo=true and rendered
   * with VideoEmbedPreview/VideoEmbedFullscreen instead of website components.
   */
  interface WebSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    favicon_url?: string;
    preview_image_url?: string;
    snippet?: string;
    description?: string;
    extra_snippets?: string | string[];
    page_age?: string;
    /** True when the result URL is a YouTube video — renders with video embed components */
    isVideo: boolean;
  }

  interface Props {
    query?: string;
    provider?: string;
    embedIds?: string | string[];
    status?: "processing" | "finished" | "error" | "cancelled";
    errorMessage?: string;
    results?: WebSearchResult[];
    previewData?: {
      query?: string;
      provider?: string;
      status?: string;
      results?: unknown[];
    };
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: "previous" | "next";
    showChatButton?: boolean;
    onShowChat?: () => void;
    initialChildEmbedId?: string;
  }

  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
    previewData,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    initialChildEmbedId,
  }: Props = $props();

  // Local reactive state for streaming updates
  let localQuery = $state("");
  let localProvider = $state("Brave Search");
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let localStatus = $state<"processing" | "finished" | "error" | "cancelled">(
    "finished",
  );
  let localErrorMessage = $state("");

  $effect(() => {
    localQuery = previewData?.query || queryProp || "";
    localProvider = previewData?.provider || providerProp || "Brave Search";
    localStatus =
      (previewData?.status as typeof localStatus) || statusProp || "finished";
    localErrorMessage = errorMessageProp || "";
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let legacyResults = $derived(previewData?.results || resultsProp || []);
  let viaProvider = $derived(`${$text("embeds.via")} ${provider}`);

  /**
   * Extract nested or flat field from decoded content
   */
  function getNestedField(
    obj: Record<string, unknown>,
    ...paths: string[]
  ): string | undefined {
    for (const path of paths) {
      if (path.includes(".")) {
        const parts = path.split(".");
        let value: unknown = obj;
        for (const part of parts) {
          if (
            value &&
            typeof value === "object" &&
            part in (value as Record<string, unknown>)
          ) {
            value = (value as Record<string, unknown>)[part];
          } else {
            value = undefined;
            break;
          }
        }
        if (typeof value === "string" && value) return value;
      } else {
        const value = obj[path];
        if (typeof value === "string" && value) return value;
      }
    }
    return undefined;
  }

  /**
   * Transform raw embed content to WebSearchResult format.
   * YouTube URLs are flagged as isVideo=true for conditional rendering.
   */
  function transformToWebResult(
    embedId: string,
    content: Record<string, unknown>,
  ): WebSearchResult {
    const faviconUrl = getNestedField(
      content,
      "meta_url.favicon",
      "favicon_url",
      "meta_url_favicon",
    );
    const thumbnailUrl = getNestedField(
      content,
      "thumbnail.original",
      "preview_image_url",
      "thumbnail_original",
      "image",
    );
    const pageAge =
      (content.age as string) || (content.page_age as string) || undefined;
    const url = content.url as string;

    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url,
      favicon_url: faviconUrl,
      preview_image_url: thumbnailUrl,
      snippet: (content.snippet as string) || (content.description as string),
      description: content.description as string | undefined,
      extra_snippets: content.extra_snippets as string | string[] | undefined,
      page_age: pageAge,
      isVideo: isYouTubeUrl(url),
    };
  }

  /**
   * Transform legacy results for backwards compatibility
   */
  function transformLegacyResults(results: unknown[]): WebSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const url = r.url as string;
      return {
        embed_id: `legacy-${i}`,
        title: r.title as string | undefined,
        url,
        favicon_url:
          (r.favicon as string) ||
          getNestedField(
            r,
            "meta_url.favicon",
            "favicon_url",
            "meta_url_favicon",
          ),
        preview_image_url: getNestedField(
          r,
          "thumbnail.original",
          "preview_image_url",
          "thumbnail_original",
          "image",
        ),
        snippet: (r.snippet as string) || (r.description as string),
        description: r.description as string | undefined,
        extra_snippets: r.extra_snippets as string | string[] | undefined,
        page_age: (r.age as string) || (r.page_age as string) || undefined,
        isVideo: isYouTubeUrl(url),
      };
    });
  }

  /**
   * Handle embed data updates during streaming
   */
  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
  }) {
    if (!data.decodedContent) return;
    const s = data.status;
    if (
      s === "processing" ||
      s === "finished" ||
      s === "error" ||
      s === "cancelled"
    )
      localStatus = s;
    const c = data.decodedContent;
    if (typeof c.query === "string") localQuery = c.query;
    if (typeof c.provider === "string") localProvider = c.provider;
    if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
    if (typeof c.error === "string") localErrorMessage = c.error;
  }
</script>

<SearchResultsTemplate
  appId="web"
  skillId="search"
  minCardWidth="260px"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToWebResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    {#if result.isVideo}
      <VideoEmbedPreview
        id={result.embed_id}
        url={result.url}
        title={result.title}
        thumbnail={result.preview_image_url}
        status="finished"
        isMobile={false}
        onFullscreen={(_metadata) => onSelect()}
      />
    {:else}
      <WebsiteEmbedPreview
        id={result.embed_id}
        url={result.url}
        title={result.title}
        description={result.snippet}
        favicon={result.favicon_url}
        image={result.preview_image_url}
        status="finished"
        isMobile={false}
        onFullscreen={onSelect}
      />
    {/if}
  {/snippet}

  {#snippet childFullscreen(nav)}
    {#if nav.result.isVideo}
      <VideoEmbedFullscreen
        url={nav.result.url}
        title={nav.result.title}
        onClose={nav.onClose}
        embedId={nav.result.embed_id}
        hasPreviousEmbed={nav.hasPrevious}
        hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious}
        onNavigateNext={nav.onNext}
      />
    {:else}
      <WebsiteEmbedFullscreen
        url={nav.result.url}
        title={nav.result.title}
        description={nav.result.description || nav.result.snippet}
        favicon={nav.result.favicon_url}
        image={nav.result.preview_image_url}
        extra_snippets={nav.result.extra_snippets}
        dataDate={nav.result.page_age}
        onClose={nav.onClose}
        embedId={nav.result.embed_id}
        hasPreviousEmbed={nav.hasPrevious}
        hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious}
        onNavigateNext={nav.onNext}
      />
    {/if}
  {/snippet}
</SearchResultsTemplate>

<style>
  :global(
    .unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="search"]
  ) {
    -webkit-mask-image: url("@openmates/ui/static/icons/search.svg");
    mask-image: url("@openmates/ui/static/icons/search.svg");
  }
</style>
