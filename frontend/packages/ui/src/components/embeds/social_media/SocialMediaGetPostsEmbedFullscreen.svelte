<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaGetPostsEmbedFullscreen.svelte

  Fullscreen grid for Social Media / Get posts parent embeds.
  Uses SearchResultsTemplate to load child post embeds and open each post in
  an overlay detail view.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import SocialMediaPostEmbedPreview from './SocialMediaPostEmbedPreview.svelte';
  import SocialMediaPostEmbedFullscreen from './SocialMediaPostEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    socialProviderLabel,
    transformLegacySocialPosts,
    transformToSocialPostResult,
  } from './socialMediaEmbedUtils';
  import { text } from '@repo/ui';

  interface Props {
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

  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Social media posts');
  let provider = $derived(socialProviderLabel(data.decodedContent?.provider));
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let resultsProp = $derived(Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : []);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);
</script>

<SearchResultsTemplate
  appId="social_media"
  skillId="get-posts"
  skillIconName="socialmedia"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToSocialPostResult}
  legacyResults={resultsProp}
  legacyResultTransformer={transformLegacySocialPosts}
  {initialChildEmbedId}
  minCardWidth="260px"
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <SocialMediaPostEmbedPreview
      id={result.embed_id}
      platform={result.platform}
      page={result.page}
      title={result.title}
      body={result.body}
      author={result.author}
      author_display_name={result.author_display_name}
      author_avatar_url={result.author_avatar_url}
      media_url={result.media_url}
      thumbnail_url={result.thumbnail_url}
      published_at={result.published_at}
      like_count={result.like_count}
      reply_count={result.reply_count}
      repost_count={result.repost_count}
      comments={result.comments}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <SocialMediaPostEmbedFullscreen
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
