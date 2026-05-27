<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedFullscreen.svelte

  Fullscreen view for one normalized Social Media post child embed.
  Extracts decoded TOON content from UnifiedEmbedFullscreen raw data and renders
  the original post card plus saved comments.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE, MAX_WIDTH_FAVICON } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { formatCount, formatPostedAt, normalizeComments, socialSourceLabel } from './socialMediaEmbedUtils';

  const LONG_POST_THRESHOLD = 900;

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
  let ctaText = $derived(platform ? `Open on ${platform.charAt(0).toUpperCase()}${platform.slice(1)}` : 'Open post');
  let favicon = $derived(avatar ? proxyImage(avatar, MAX_WIDTH_FAVICON) : undefined);
  let isExpanded = $state(false);
  let shouldClampPost = $derived(body.length > LONG_POST_THRESHOLD && !isExpanded);
  let postedAt = $derived(formatPostedAt(publishedAt));

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
      <EmbedHeaderCtaButton href={url} text={ctaText} />
    {/if}
  {/snippet}

  {#snippet content()}
    <article class="social-post-fullscreen">
      <section class="original-post-card" aria-label="Original social media post">
        <header class="post-header">
          {#if favicon}
            <img class="avatar" src={favicon} alt="" use:handleImageError />
          {:else}
            <div class="avatar fallback-avatar">{authorDisplayName.slice(0, 1).toUpperCase()}</div>
          {/if}
          <div class="author-block">
            <div class="author-name">{authorDisplayName}</div>
            <div class="post-source">
              {#if author}<span>@{author}</span>{/if}
              {#if author && (postedAt || source)}<span>·</span>{/if}
              <span>{postedAt || source}</span>
            </div>
          </div>
        </header>

        <div class="post-content">
          {#if title && title !== body}
            <h1>{title}</h1>
          {/if}
          {#if body}
            <p class:clamped={shouldClampPost}>{body}</p>
            {#if body.length > LONG_POST_THRESHOLD}
              <button class="expand-button" type="button" onclick={() => (isExpanded = !isExpanded)}>
                {isExpanded ? 'Show less' : 'Expand post'}
              </button>
            {/if}
          {/if}
        </div>

        {#if mediaUrl}
          <img class="media" src={proxyImage(mediaUrl, MAX_WIDTH_HEADER_IMAGE)} alt="" use:handleImageError />
        {/if}

        {#if externalUrl || externalTitle}
          <a class="external-card" href={externalUrl || url} target="_blank" rel="noopener noreferrer">
            <span>{externalTitle || externalUrl}</span>
          </a>
        {/if}

        <footer class="metrics">
          <span>{formatCount(dc.like_count as number | undefined)} likes</span>
          <span>{formatCount(dc.reply_count as number | undefined)} replies</span>
          <span>{formatCount(dc.repost_count as number | undefined)} reposts</span>
        </footer>
      </section>

      <section class="comments">
        <div class="section-heading">
          <h2>Comments</h2>
          <span>{comments.length} saved</span>
        </div>
        {#if comments.length > 0}
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
        {:else}
          <div class="empty-comments">No comments were saved for this post.</div>
        {/if}
      </section>
    </article>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .social-post-fullscreen {
    width: min(820px, calc(100% - 32px));
    margin: 0 auto;
    padding: var(--spacing-12) 0 120px;
  }

  .original-post-card,
  .comments {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-xl);
    background: var(--color-surface-primary);
    box-shadow: 0 16px 40px color-mix(in srgb, var(--color-shadow, #000) 10%, transparent);
  }

  .original-post-card {
    overflow: hidden;
  }

  .post-header {
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
    padding: var(--spacing-8) var(--spacing-8) 0;
  }

  .avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    object-fit: cover;
    flex: 0 0 auto;
  }

  .fallback-avatar {
    display: grid;
    place-items: center;
    background: var(--color-app-socialmedia, var(--color-primary));
    color: var(--color-font-button);
    font-weight: 800;
  }

  .author-block {
    min-width: 0;
  }

  .author-name {
    color: var(--color-text-primary);
    font-size: var(--font-size-md);
    font-weight: 700;
  }

  .post-source {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .post-content {
    padding: var(--spacing-7) var(--spacing-8) var(--spacing-6);
  }

  .metrics {
    display: flex;
    align-items: center;
    gap: var(--spacing-6);
    flex-wrap: wrap;
    padding: var(--spacing-5) var(--spacing-8);
    border-top: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  h1 {
    margin: 0 0 var(--spacing-5);
    color: var(--color-text-primary);
    font-size: clamp(1.35rem, 2.2vw, 1.95rem);
    line-height: 1.18;
  }

  .post-content p {
    margin: 0;
    color: var(--color-text-primary);
    font-size: var(--font-size-md);
    line-height: 1.6;
    white-space: pre-wrap;
  }

  .post-content p.clamped {
    display: -webkit-box;
    -webkit-line-clamp: 9;
    line-clamp: 9;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .expand-button {
    margin-top: var(--spacing-5);
    border: 0;
    background: transparent;
    color: var(--color-button-primary);
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }

  .media {
    width: 100%;
    max-height: 520px;
    object-fit: contain;
    border-top: 1px solid var(--color-border);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-grey-15);
  }

  .external-card {
    display: block;
    margin: 0 var(--spacing-8) var(--spacing-6);
    padding: var(--spacing-5);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface-secondary);
    color: var(--color-text-primary);
    text-decoration: none;
  }

  .comments {
    margin-top: var(--spacing-8);
    padding: var(--spacing-8);
  }

  .section-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--spacing-4);
    margin-bottom: var(--spacing-6);
  }

  .section-heading h2 {
    margin: 0;
    color: var(--color-text-primary);
    font-size: var(--font-size-lg);
  }

  .section-heading span,
  .empty-comments {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .comment {
    padding: var(--spacing-5) 0;
    border-top: 1px solid var(--color-border);
  }

  .section-heading + .comment {
    border-top: 0;
    padding-top: 0;
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
    white-space: pre-wrap;
  }

  @media (max-width: 640px) {
    .social-post-fullscreen {
      width: min(100% - 20px, 820px);
      padding-top: var(--spacing-6);
    }

    .post-header,
    .post-content,
    .comments {
      padding-left: var(--spacing-5);
      padding-right: var(--spacing-5);
    }

    .external-card {
      margin-left: var(--spacing-5);
      margin-right: var(--spacing-5);
    }
  }
</style>
