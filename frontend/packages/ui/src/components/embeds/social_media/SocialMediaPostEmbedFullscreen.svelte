<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedFullscreen.svelte

  Fullscreen view for one normalized Social Media post child embed.
  Extracts decoded TOON content from UnifiedEmbedFullscreen raw data and renders
  the post text, metrics, media, and comments.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE, MAX_WIDTH_FAVICON } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { formatCount, normalizeComments, socialSourceLabel } from './socialMediaEmbedUtils';

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

  let dc = $derived(data.decodedContent ?? {});
  let platform = $derived(asString(dc.platform));
  let page = $derived(asString(dc.page));
  let title = $derived(asString(dc.title) || 'Social post');
  let body = $derived(asString(dc.body) || '');
  let author = $derived(asString(dc.author));
  let authorDisplayName = $derived(asString(dc.author_display_name) || author || page || platform || 'Social Media');
  let avatar = $derived(asString(dc.author_avatar_url));
  let url = $derived(asString(dc.url));
  let publishedAt = $derived(asString(dc.published_at));
  let mediaUrl = $derived(asString(dc.media_url) || asString(dc.thumbnail_url));
  let externalUrl = $derived(asString(dc.external_url));
  let externalTitle = $derived(asString(dc.external_title));
  let comments = $derived(normalizeComments(dc.comments));
  let source = $derived(socialSourceLabel({ embed_id: embedId || '', platform, page }));
  let favicon = $derived(avatar ? proxyImage(avatar, MAX_WIDTH_FAVICON) : undefined);

  function asString(value: unknown): string | undefined {
    return typeof value === 'string' && value.trim() ? value : undefined;
  }
</script>

<UnifiedEmbedFullscreen
  appId="social_media"
  skillId="social_post"
  embedHeaderTitle={title}
  embedHeaderSubtitle={source}
  embedHeaderFaviconUrl={favicon}
  skillIconName="socialmedia"
  showSkillIcon={!favicon}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet embedHeaderCta()}
    {#if url}
      <EmbedHeaderCtaButton href={url} text="Open post" />
    {/if}
  {/snippet}

  {#snippet content()}
    <article class="social-post-fullscreen">
      <header class="post-header">
        {#if favicon}
          <img class="avatar" src={favicon} alt="" use:handleImageError />
        {/if}
        <div>
          <div class="author-name">{authorDisplayName}</div>
          <div class="post-source">
            {#if author}@{author}{/if}{#if author && publishedAt} - {/if}{publishedAt || source}
          </div>
        </div>
      </header>

      <h1>{title}</h1>
      {#if body}
        <p class="body">{body}</p>
      {/if}

      <div class="metrics">
        <span>Likes {formatCount(dc.like_count as number | undefined)}</span>
        <span>Replies {formatCount(dc.reply_count as number | undefined)}</span>
        <span>Reposts {formatCount(dc.repost_count as number | undefined)}</span>
      </div>

      {#if mediaUrl}
        <img class="media" src={proxyImage(mediaUrl, MAX_WIDTH_HEADER_IMAGE)} alt="" use:handleImageError />
      {/if}

      {#if externalUrl || externalTitle}
        <a class="external-card" href={externalUrl} target="_blank" rel="noopener noreferrer">
          <span>{externalTitle || externalUrl}</span>
        </a>
      {/if}

      {#if comments.length > 0}
        <section class="comments">
          <h2>Comments</h2>
          {#each comments as comment, index (comment.url || `${comment.author || 'comment'}-${index}`)}
            <div class="comment">
              <div class="comment-author">
                <span>{comment.author ? `@${comment.author}` : 'Comment'}</span>
                {#if typeof comment.score === 'number' || typeof comment.ups === 'number'}
                  <span>{formatCount(comment.ups ?? comment.score)} points</span>
                {/if}
              </div>
              <p>{comment.body}</p>
            </div>
          {/each}
        </section>
      {/if}
    </article>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .social-post-fullscreen {
    width: min(760px, calc(100% - 32px));
    margin: 0 auto;
    padding: var(--spacing-12) 0 120px;
  }

  .post-header,
  .metrics {
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
  }

  .avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    object-fit: cover;
  }

  .author-name {
    color: var(--color-text-primary);
    font-size: var(--font-size-md);
    font-weight: 700;
  }

  .post-source,
  .metrics {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  h1 {
    margin: var(--spacing-8) 0 var(--spacing-5);
    color: var(--color-text-primary);
    font-size: clamp(1.6rem, 3vw, 2.4rem);
    line-height: 1.08;
  }

  .body {
    margin: 0 0 var(--spacing-7);
    color: var(--color-text-primary);
    font-size: var(--font-size-md);
    line-height: 1.65;
    white-space: pre-wrap;
  }

  .metrics {
    margin-bottom: var(--spacing-8);
    flex-wrap: wrap;
  }

  .media {
    width: 100%;
    max-height: 520px;
    object-fit: contain;
    border-radius: var(--radius-xl);
    background: var(--color-grey-15);
  }

  .external-card,
  .comment {
    display: block;
    margin-top: var(--spacing-7);
    padding: var(--spacing-7);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface-secondary);
    color: var(--color-text-primary);
    text-decoration: none;
  }

  .comments {
    margin-top: var(--spacing-10);
  }

  .comments h2 {
    color: var(--color-text-primary);
    font-size: var(--font-size-lg);
  }

  .comment-author {
    display: flex;
    justify-content: space-between;
    gap: var(--spacing-4);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    font-weight: 650;
  }

  .comment p {
    margin: var(--spacing-2) 0 0;
    color: var(--color-text-primary);
    line-height: 1.5;
  }
</style>
