/**
 * frontend/packages/ui/src/components/embeds/social_media/socialMediaEmbedUtils.ts
 *
 * Shared normalization helpers for Social Media embeds.
 * Backend providers return Reddit and Bluesky fields with small differences;
 * these helpers keep parent fullscreen components focused on rendering.
 *
 * Architecture: docs/architecture/apps/social-media.md
 */

export interface SocialMediaPostResult {
  embed_id: string;
  platform?: string;
  page?: string;
  title?: string;
  body?: string;
  author?: string;
  author_display_name?: string;
  author_avatar_url?: string;
  url?: string;
  published_at?: string;
  like_count?: number;
  reply_count?: number;
  repost_count?: number;
  quote_count?: number;
  media_url?: string;
  thumbnail_url?: string;
  external_url?: string;
  external_title?: string;
  comments?: unknown[];
  fetched_comment_count?: number;
}

export function transformToSocialPostResult(
  embedId: string,
  content: Record<string, unknown>,
): SocialMediaPostResult {
  return {
    embed_id: embedId,
    platform: asString(content.platform),
    page: asString(content.page),
    title: asString(content.title),
    body: asString(content.body),
    author: asString(content.author),
    author_display_name: asString(content.author_display_name),
    author_avatar_url: asString(content.author_avatar_url),
    url: asString(content.url),
    published_at: asString(content.published_at),
    like_count: asNumber(content.like_count),
    reply_count: asNumber(content.reply_count),
    repost_count: asNumber(content.repost_count),
    quote_count: asNumber(content.quote_count),
    media_url: asString(content.media_url),
    thumbnail_url: asString(content.thumbnail_url),
    external_url: asString(content.external_url),
    external_title: asString(content.external_title),
    comments: Array.isArray(content.comments) ? content.comments : undefined,
    fetched_comment_count: asNumber(content.fetched_comment_count),
  };
}

export function transformLegacySocialPosts(results: unknown[]): SocialMediaPostResult[] {
  const posts: SocialMediaPostResult[] = [];
  for (const [groupIndex, item] of results.entries()) {
    if (!item || typeof item !== 'object') continue;
    const group = item as Record<string, unknown>;
    const nestedPosts = Array.isArray(group.posts)
      ? group.posts
      : Array.isArray(group.results)
        ? group.results
        : null;
    if (nestedPosts) {
      for (const [postIndex, post] of nestedPosts.entries()) {
        if (!post || typeof post !== 'object') continue;
        posts.push(transformToSocialPostResult(`legacy-${groupIndex}-${postIndex}`, {
          platform: group.platform,
          page: group.page ?? group.query,
          ...(post as Record<string, unknown>),
        }));
      }
      continue;
    }
    posts.push(transformToSocialPostResult(`legacy-${groupIndex}`, group));
  }
  return posts;
}

export function socialProviderLabel(provider: unknown): string {
  const value = asString(provider);
  if (!value) return 'Social Media';
  return value
    .split(',')
    .map((part) => part.trim().replace(/_/g, ' '))
    .filter(Boolean)
    .join(', ');
}

export function socialSourceLabel(post: SocialMediaPostResult): string {
  const platform = post.platform ? titleCase(post.platform) : 'Social';
  return post.page ? `${platform} / ${post.page}` : platform;
}

export function formatCount(value: number | undefined): string {
  if (!value) return '0';
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
