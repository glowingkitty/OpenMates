<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedPreview.svelte

  Preview card for one normalized Social Media post child embed.
  Uses UnifiedEmbedPreview for consistent card behavior and only supplies
  the post-specific body snippet.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">

  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import EmbedTimePill from '@repo/public-site/components/results/EmbedTimePill.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import { proxyImage, MAX_WIDTH_FAVICON } from '../../../utils/imageProxy';
  import { formatCount, socialSourceLabel, type SocialMediaPostResult } from './socialMediaEmbedUtils';

  interface Props extends Partial<SocialMediaPostResult> {
    id?: string;
    status?: 'processing' | 'finished' | 'error';
    taskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }

  let {
    id = '',
    body,
    platform,
    page,
    title,
    author,
    author_display_name,
    author_avatar_url,
    media_url,
    thumbnail_url,
    published_at,
    like_count,
    reply_count,
    repost_count,
    status = 'finished',
    taskId,
    isMobile = false,
    presentationOnly = false,
    resultContext = 'auto',
    onFullscreen,
  }: Props = $props();

  let avatar = $derived(author_avatar_url ? proxyImage(author_avatar_url, MAX_WIDTH_FAVICON) : undefined);
  let image = $derived(proxyImage(media_url || thumbnail_url, 960));
  let displayAuthor = $derived(author_display_name || author || page || platform || 'Social post');
  let source = $derived(socialSourceLabel({ embed_id: id, platform, page }));

  const publication = $derived.by(() => {
    if (!published_at) return undefined;
    const timestamp = new Date(published_at);
    if (Number.isNaN(timestamp.getTime())) return undefined;
    return {
      iso: timestamp.toISOString(),
      label: new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(timestamp),
    };
  });

  function handleStop() {
    // Child posts are already resolved server-side.
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {presentationOnly}
  {resultContext}
  {id}
  appId="social_media"
  skillId="social_post"
  skillIconName="socialmedia"
  {status}
  skillName={displayAuthor}
  {isMobile}
  showSkillIcon={!avatar}
  faviconUrl={avatar}
  showStatus={false}
  {taskId}
  {onFullscreen}
  onStop={handleStop}
>

  {#snippet details()}
    <div data-testid="social-post-preview" class="catalog-result-preview">
      <ResultEmbedCard title={title || displayAuthor} description={body} sourceLabel={[displayAuthor, source].filter(Boolean).join(" · ")} faviconUrl={avatar} imageUrl={image} imageAlt={title || displayAuthor} mediaFit="contain">
        {#snippet badge()}{#if publication}<EmbedTimePill label={publication.label} datetime={publication.iso} testId="social-post-publication-date" />{/if}{/snippet}
        {#snippet facts()}{#if like_count != null}<ResultEmbedInfo icon="Heart" label="Likes" value={formatCount(like_count)}>{#snippet children()}{formatCount(like_count)} likes{/snippet}</ResultEmbedInfo>{/if}
{#if reply_count != null}<ResultEmbedInfo icon="MessageCircle" label="Replies" value={formatCount(reply_count)}>{#snippet children()}{formatCount(reply_count)} replies{/snippet}</ResultEmbedInfo>{/if}
{#if repost_count != null}<ResultEmbedInfo icon="Repeat2" label="Reposts" value={formatCount(repost_count)}>{#snippet children()}{formatCount(repost_count)} reposts{/snippet}</ResultEmbedInfo>{/if}{/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .catalog-result-preview { width: 100%; height: 100%; min-width: 0; }
</style>
