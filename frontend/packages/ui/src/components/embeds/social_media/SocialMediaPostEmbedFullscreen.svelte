<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedFullscreen.svelte

  Fullscreen view for one normalized Social Media post child embed.
  Extracts decoded TOON content from UnifiedEmbedFullscreen raw data and renders
  the original post card plus saved comments.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
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

<ResultEmbedFullscreen
  result={Object.fromEntries(["platform", "page", "title", "body", "author", "url", "published_at", "like_count", "reply_count", "repost_count"].filter(key => dc[key] !== undefined).map(key => [key, dc[key]]))}
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
      <EmbedHeaderCtaButton href={url} label={ctaText} />
    {/if}
  {/snippet}

  {#snippet summary()}{#each [['like_count', 'Heart', 'Likes'], ['reply_count', 'MessageCircle', 'Replies'], ['repost_count', 'Repeat2', 'Reposts']] as [key, icon, label]}
{#if typeof dc[key] === 'number'}<ResultEmbedInfo {icon} {label} value={formatCount(dc[key] as number)}>{#snippet children()}{label}: {formatCount(dc[key] as number)}{/snippet}</ResultEmbedInfo>{/if}{/each}{/snippet}

  {#snippet media()}        {#if mediaUrl}
          <img class="media" src={proxyImage(mediaUrl, MAX_WIDTH_HEADER_IMAGE)} alt="" use:handleImageError />
        {/if}

  {/snippet}
  {#snippet detailContent()}
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

        {#if externalUrl || externalTitle}
          <a class="external-card" href={externalUrl || url} target="_blank" rel="noopener noreferrer">
            <span>{externalTitle || externalUrl}</span>
          </a>
        {/if}

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
</ResultEmbedFullscreen>

<style>
 .social-post-fullscreen {display:flex;flex-direction:column;gap:var(--spacing-6);width:100%;} .post-header {display:flex;align-items:center;gap:var(--spacing-3);} .avatar {width:36px;height:36px;border-radius:50%;object-fit:cover;} .fallback-avatar {display:grid;place-items:center;background:var(--color-grey-20);} .author-name {font-weight:600;} .post-source,.comment-author,.section-heading {display:flex;flex-wrap:wrap;gap:var(--spacing-2);color:var(--color-font-secondary);font-size:var(--font-size-small);} .post-content {margin-top:var(--spacing-4);} h1,h2 {margin:0 0 var(--spacing-3);font-size:var(--font-size-h4);overflow-wrap:anywhere;} p {margin:0;white-space:pre-wrap;line-height:1.5;overflow-wrap:anywhere;} .clamped {display:-webkit-box;-webkit-line-clamp:9;-webkit-box-orient:vertical;overflow:hidden;} .expand-button {margin-top:var(--spacing-3);border:0;background:transparent;color:var(--color-link);cursor:pointer;min-height:44px;} .media {display:block;width:100%;height:auto;max-height:60vh;object-fit:contain;} .external-card {display:block;color:var(--color-link);margin-top:var(--spacing-4);overflow-wrap:anywhere;} .section-heading {justify-content:space-between;align-items:center;} .section-heading h2 {margin:0;} .comment {padding-block:var(--spacing-4);border-top:1px solid var(--color-grey-20);} .comment p {margin-top:var(--spacing-2);} .empty-comments {margin-top:var(--spacing-3);color:var(--color-font-secondary);}
</style>
