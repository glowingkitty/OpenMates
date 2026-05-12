/**
 * frontend/packages/ui/src/components/embeds/social_media/socialMediaEmbedText.ts
 *
 * Plain-text renderers for Social Media embeds.
 * Used by copy/export paths where Svelte components are not available.
 * Keep output compact enough for chat exports and CLI rendering.
 *
 * Architecture: docs/architecture/apps/social-media.md
 */

import { resolveResultCount, str, trunc } from '../../../data/embedTextRenderers';

export function renderSocialMediaGetPosts(
  content: Record<string, unknown>,
  children?: Record<string, unknown>[],
): string {
  return renderSocialMediaCollection('Social media posts', content, children);
}

export function renderSocialMediaSearch(
  content: Record<string, unknown>,
  children?: Record<string, unknown>[],
): string {
  return renderSocialMediaCollection('Social media search', content, children);
}

export function renderSocialMediaPost(content: Record<string, unknown>): string {
  const title = str(content.title) ?? 'Social post';
  const author = str(content.author_display_name) ?? str(content.author);
  const platform = str(content.platform);
  const body = str(content.body);
  const url = str(content.url);
  const lines = [`**${title}**`];
  const byline = [author, platform].filter(Boolean).join(' - ');
  if (byline) lines.push(byline);
  if (body) lines.push(trunc(body, 240));
  if (url) lines.push(url);
  return lines.join('\n');
}

function renderSocialMediaCollection(
  fallbackTitle: string,
  content: Record<string, unknown>,
  children?: Record<string, unknown>[],
): string {
  const query = str(content.query) ?? fallbackTitle;
  const count = children?.length ?? resolveResultCount(content) ?? 0;
  const lines = [`**${query}**`, `${count} post${count === 1 ? '' : 's'}`];
  if (children?.length) {
    for (const child of children.slice(0, 5)) {
      const title = str(child.title) ?? str(child.body);
      if (title) lines.push(`- ${trunc(title, 100)}`);
    }
  }
  return lines.join('\n');
}
