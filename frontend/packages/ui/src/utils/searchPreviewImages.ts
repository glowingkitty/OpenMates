/**
 * Shared image selection for search result previews and chat headers.
 * Supports normalized parent metadata and legacy child result formats.
 * Keeps URL choice consistent across web, news, and image search.
 * Callers proxy the selected URL at the size appropriate to their surface.
 * Architecture: docs/architecture/embeds.md
 */
export const SEARCH_PREVIEW_IMAGE_LIMIT = 10;

export function searchResultImageUrl(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const result = value as Record<string, unknown>;
  const thumbnail = result.thumbnail && typeof result.thumbnail === 'object'
    ? result.thumbnail as Record<string, unknown> : {};
  return [result.thumbnail_url, result.preview_image_url, result.image_url,
    result.thumbnail_original, thumbnail.original, result['thumbnail.original'],
    result.thumbnail_src, thumbnail.src, result['thumbnail.src'], result.thumbnail, result.image]
    .filter((url): url is string => typeof url === 'string')
    .map(url => url.trim())
    .find(url => url.length > 0 && url !== 'null' && url !== 'undefined');
}

export function searchPreviewImages(results: readonly unknown[]) {
  const seen = new Set<string>();
  const images: Array<{ url: string; title: string }> = [];
  for (const result of results) {
    const url = searchResultImageUrl(result);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    const title = (result as { title?: unknown }).title;
    images.push({ url, title: typeof title === 'string' ? title : '' });
    if (images.length === SEARCH_PREVIEW_IMAGE_LIMIT) break;
  }
  return images;
}

/** Visible legacy parents may lack images even when their children contain them.
 * Reuse the caller's cached embed resolver; never load children on the metadata path.
 */
export async function resolveSearchPreviewImages(
  results: readonly unknown[],
  childEmbedIds: readonly string[],
  loadChild: (id: string) => Promise<unknown>,
  signal?: AbortSignal,
) {
  if (signal?.aborted) return [];
  const images = searchPreviewImages(results);
  if (images.length > 0) return images;
  const ids = Array.from(new Set(childEmbedIds)).slice(0, SEARCH_PREVIEW_IMAGE_LIMIT);
  const children = await Promise.allSettled(ids.map(loadChild));
  if (signal?.aborted) return [];
  const content: unknown[] = [];
  for (const child of children) {
    if (child.status === 'fulfilled') content.push(child.value);
    else console.warn('[searchPreviewImages] Could not resolve a child image:', child.reason);
  }
  return searchPreviewImages(content);
}
