<!--
  frontend/packages/ui/src/components/embeds/videos/VideosSearchEmbedFullscreen.svelte

  Fullscreen view for Videos Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with search query and "via {provider}"
  - Video cards in responsive grid (VideoEmbedPreview)
  - Drill-down: clicking a card opens VideoEmbedFullscreen overlay with sibling nav

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.
  VideoEmbedFullscreen extracts all metadata from data.decodedContent.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import VideoEmbedPreview from './VideoEmbedPreview.svelte';
  import VideoEmbedFullscreen from './VideoEmbedFullscreen.svelte';

  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  /**
   * Video search result interface (transformed from child embeds)
   */
  interface VideoSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    thumbnail?: string;
    channelThumbnail?: string;
    channelName?: string;
    channelId?: string;
    description?: string;
    durationSeconds?: number;
    durationFormatted?: string;
    viewCount?: number;
    likeCount?: number;
    publishedAt?: string;
    videoId?: string;
  }

  interface Props {
    /** Raw embed data — component extracts its own fields internally */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // Extract fields from data prop
  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '');
  let provider = $derived(typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Brave');
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let resultsProp = $derived(Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : []);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  /**
   * Parse ISO 8601 duration string to seconds and formatted string.
   */
  function parseIsoDuration(isoDuration: string | undefined): { totalSeconds: number; formatted: string } | undefined {
    if (!isoDuration || typeof isoDuration !== 'string') return undefined;
    const match = isoDuration.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
    if (!match) return undefined;
    const hours = parseInt(match[1] || '0', 10);
    const minutes = parseInt(match[2] || '0', 10);
    const seconds = parseInt(match[3] || '0', 10);
    const totalSeconds = hours * 3600 + minutes * 60 + seconds;
    let formatted: string;
    if (hours > 0) {
      formatted = `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    } else {
      formatted = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
    return { totalSeconds, formatted };
  }

  /**
   * Extract video ID from YouTube URL.
   */
  function extractVideoId(videoUrl: string): string | undefined {
    if (!videoUrl) return undefined;
    const patterns = [
      /(?:youtube\.com\/watch\?.*v=)([a-zA-Z0-9_-]{11})/,
      /(?:youtu\.be\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/,
    ];
    for (const pattern of patterns) {
      const match = videoUrl.match(pattern);
      if (match) return match[1];
    }
    return undefined;
  }

  /**
   * Transform raw embed content to VideoSearchResult format.
   */
  function transformToVideoResult(embedId: string, content: Record<string, unknown>): VideoSearchResult {
    const thumbnail = content.thumbnail as Record<string, string> | undefined;
    const metaUrl = content.meta_url as Record<string, string> | undefined;
    const url = content.url as string || '';
    const duration = parseIsoDuration(content.duration as string | undefined);
    const videoId = extractVideoId(url);

    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url,
      thumbnail: (content.thumbnail_original as string) || thumbnail?.original || thumbnail?.src,
      channelThumbnail: (content.meta_url_profile_image as string) || metaUrl?.profile_image,
      channelName: content.channelTitle as string | undefined,
      channelId: content.channelId as string | undefined,
      description: (content.description as string) || (content.snippet as string),
      durationSeconds: duration?.totalSeconds,
      durationFormatted: duration?.formatted,
      viewCount: content.viewCount as number | undefined,
      likeCount: content.likeCount as number | undefined,
      publishedAt: content.publishedAt as string | undefined,
      videoId,
    };
  }

  /**
   * Transform legacy results for backwards compatibility.
   */
  function transformLegacyResults(results: unknown[]): VideoSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const thumbnail = r.thumbnail as Record<string, string> | undefined;
      const metaUrl = r.meta_url as Record<string, string> | undefined;
      const url = r.url as string || '';
      const duration = parseIsoDuration(r.duration as string | undefined);
      const videoId = extractVideoId(url);

      return {
        embed_id: `legacy-${i}`,
        title: r.title as string | undefined,
        url,
        thumbnail: (r.thumbnail_original as string) || thumbnail?.original || thumbnail?.src,
        channelThumbnail: (r.meta_url_profile_image as string) || metaUrl?.profile_image,
        channelName: r.channelTitle as string | undefined,
        channelId: r.channelId as string | undefined,
        description: (r.description as string) || (r.snippet as string),
        durationSeconds: duration?.totalSeconds,
        durationFormatted: duration?.formatted,
        viewCount: r.viewCount as number | undefined,
        likeCount: r.likeCount as number | undefined,
        publishedAt: r.publishedAt as string | undefined,
        videoId,
      };
    });
  }

</script>

<SearchResultsTemplate
  appId="videos"
  skillId="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToVideoResult}
  legacyResults={resultsProp}
  legacyResultTransformer={transformLegacyResults}
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
    <VideoEmbedPreview
      id={result.embed_id}
      url={result.url}
      title={result.title}
      status="finished"
      isMobile={false}
      channelName={result.channelName}
      channelId={result.channelId}
      channelThumbnail={result.channelThumbnail}
      thumbnail={result.thumbnail}
      durationSeconds={result.durationSeconds}
      durationFormatted={result.durationFormatted}
      viewCount={result.viewCount}
      likeCount={result.likeCount}
      publishedAt={result.publishedAt}
      videoId={result.videoId}
      onFullscreen={() => {
        onSelect();
      }}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <VideoEmbedFullscreen
      data={{ decodedContent: nav.result }}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>
