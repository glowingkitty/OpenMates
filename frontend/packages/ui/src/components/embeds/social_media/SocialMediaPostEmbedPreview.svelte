<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedPreview.svelte

  Preview card for one normalized Social Media post child embed.
  Uses UnifiedEmbedPreview for consistent card behavior and only supplies
  the post-specific body snippet.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_FAVICON } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { formatCount, socialSourceLabel, type SocialMediaPostResult } from './socialMediaEmbedUtils';

  interface Props extends Partial<SocialMediaPostResult> {
    id?: string;
    status?: 'processing' | 'finished' | 'error';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id = '',
    platform,
    page,
    title,
    body,
    author,
    author_display_name,
    author_avatar_url,
    media_url,
    thumbnail_url,
    like_count,
    reply_count,
    repost_count,
    status = 'finished',
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let avatar = $derived(author_avatar_url ? proxyImage(author_avatar_url, MAX_WIDTH_FAVICON) : undefined);
  let image = $derived(media_url || thumbnail_url);
  let displayAuthor = $derived(author_display_name || author || page || platform || 'Social post');
  let source = $derived(socialSourceLabel({ embed_id: id, platform, page }));
  let text = $derived(body || title || '');

  function handleStop() {
    // Child posts are already resolved server-side.
  }
</script>

<UnifiedEmbedPreview
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
    <div class="social-post-preview">
      <div class="post-meta">
        <span class="source">{source}</span>
        {#if author}
          <span class="author">@{author}</span>
        {/if}
      </div>
      <div class="post-title">{title || displayAuthor}</div>
      {#if text}
        <p class="post-body">{text}</p>
      {/if}
      <div class="post-footer">
        <span>Likes {formatCount(like_count)}</span>
        <span>Replies {formatCount(reply_count)}</span>
        <span>Reposts {formatCount(repost_count)}</span>
      </div>
      {#if image}
        <img class="post-image" src={image} alt="" use:handleImageError />
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .social-post-preview {
    position: relative;
    display: flex;
    height: 100%;
    flex-direction: column;
    gap: var(--spacing-3);
    padding: var(--spacing-7);
    overflow: hidden;
  }

  .post-meta,
  .post-footer {
    display: flex;
    gap: var(--spacing-4);
    align-items: center;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xxs);
    min-width: 0;
  }

  .source,
  .author {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .post-title {
    color: var(--color-text-primary);
    font-size: var(--font-size-sm);
    font-weight: 650;
    line-height: 1.25;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .post-body {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .post-footer {
    margin-top: auto;
  }

  .post-image {
    position: absolute;
    right: var(--spacing-5);
    bottom: var(--spacing-5);
    width: 54px;
    height: 54px;
    object-fit: cover;
    border-radius: var(--radius-md);
    opacity: 0.88;
  }
</style>
