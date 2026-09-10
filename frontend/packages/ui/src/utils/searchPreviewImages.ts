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
    result.thumbnail_original, thumbnail.original, result.thumbnail_src, thumbnail.src]
    .find((url): url is string => typeof url === 'string' && url.trim().length > 0);
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
