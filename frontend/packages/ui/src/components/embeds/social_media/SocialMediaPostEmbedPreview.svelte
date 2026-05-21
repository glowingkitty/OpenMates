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
  import { formatCount, formatPostedAt, socialSourceLabel, type SocialMediaPostResult } from './socialMediaEmbedUtils';

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
    published_at,
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
  let postedAt = $derived(formatPostedAt(published_at));

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
      <div class="post-author-row">
        {#if avatar}
          <img class="avatar" src={avatar} alt="" use:handleImageError />
        {:else}
          <div class="avatar avatar-fallback">{displayAuthor.slice(0, 1).toUpperCase()}</div>
        {/if}
        <div class="post-heading">
          <div class="post-title">{title || displayAuthor}</div>
          <div class="post-meta">
            <span class="source">{source}</span>
            {#if postedAt}
              <span>·</span>
              <span>{postedAt}</span>
            {/if}
          </div>
        </div>
      </div>
      {#if text}
        <p class="post-body">{text}</p>
      {/if}
      <div class="post-footer">
        <span>{formatCount(like_count)} likes</span>
        <span>{formatCount(reply_count)} comments</span>
        {#if typeof repost_count === 'number' && repost_count > 0}
          <span>{formatCount(repost_count)} reposts</span>
        {/if}
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
    gap: var(--spacing-4);
    padding: var(--spacing-7);
    overflow: hidden;
  }

  .post-author-row {
    display: flex;
    gap: var(--spacing-4);
    align-items: flex-start;
    min-width: 0;
  }

  .avatar {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    object-fit: cover;
    flex: 0 0 auto;
  }

  .avatar-fallback {
    display: grid;
    place-items: center;
    background: var(--color-app-socialmedia, var(--color-primary));
    color: var(--color-font-button);
    font-weight: 800;
  }

  .post-heading {
    min-width: 0;
  }

  .post-meta,
  .post-footer {
    display: flex;
    gap: var(--spacing-2);
    align-items: center;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xxs);
    min-width: 0;
  }

  .source {
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
    gap: var(--spacing-5);
    padding-top: var(--spacing-3);
    border-top: 1px solid var(--color-border);
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
