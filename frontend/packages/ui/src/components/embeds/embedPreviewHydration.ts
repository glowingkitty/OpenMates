// frontend/packages/ui/src/components/embeds/embedPreviewHydration.ts
// Pure helpers for keeping embed preview hydration bounded.
// Components use these helpers to avoid resolving hidden carousel slides during
// initial chat render. Parent previews must remain self-contained and must not
// hydrate child embeds as a fallback.
// Covered by embedPreviewHydration.test.ts.

export const DEFAULT_CAROUSEL_HYDRATION_OVERSCAN = 1;
export const DEFAULT_PARENT_PREVIEW_METADATA_LIMIT = 6;

export type ParentPreviewResultState =
  | 'not_finished'
  | 'has_preview_metadata'
  | 'known_zero_results'
  | 'missing_preview_metadata';

interface ParentPreviewResultStateOptions {
  status?: string;
  previewResultCount: number;
  resultCount?: number;
  childEmbedIds?: string[];
}

export interface WebSearchPreviewResult {
  title?: string;
  url: string;
  favicon?: string;
  favicon_url?: string;
  meta_url?: { favicon?: string };
  preview_image_url?: string;
  snippet?: string;
}

export interface ImageSearchPreviewResult {
  title?: string;
  source_page_url?: string;
  image_url?: string;
  thumbnail_url?: string;
  source?: string;
  favicon_url?: string;
}

function normalizeCarouselIndex(index: number, total: number): number {
  return ((index % total) + total) % total;
}

export function shouldHydrateCarouselSlide(
  currentIndex: number,
  carouselIndex: number,
  carouselTotal: number,
  overscan = DEFAULT_CAROUSEL_HYDRATION_OVERSCAN,
): boolean {
  if (carouselTotal <= 1) return true;

  const normalizedCurrent = normalizeCarouselIndex(currentIndex, carouselTotal);
  const normalizedSlide = normalizeCarouselIndex(carouselIndex, carouselTotal);
  const distance = Math.abs(normalizedCurrent - normalizedSlide);
  const wrappedDistance = carouselTotal - distance;

  return Math.min(distance, wrappedDistance) <= overscan;
}

export function normalizeEmbedIdList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((id): id is string => typeof id === 'string' && id.trim().length > 0);
  }

  if (typeof value !== 'string') return [];

  const trimmed = value.trim();
  if (!trimmed || trimmed === '[]' || trimmed === 'null' || trimmed === 'undefined') return [];

  if (trimmed.startsWith('[')) {
    try {
      return normalizeEmbedIdList(JSON.parse(trimmed));
    } catch {
      // Fall through to legacy pipe-separated parsing.
    }
  }

  return trimmed.split('|').map((id) => id.trim()).filter(Boolean);
}

export function getParentPreviewResultState({
  status,
  previewResultCount,
  resultCount,
  childEmbedIds = [],
}: ParentPreviewResultStateOptions): ParentPreviewResultState {
  if (status !== 'finished') return 'not_finished';
  if (previewResultCount > 0) return 'has_preview_metadata';
  if (childEmbedIds.length > 0 || (typeof resultCount === 'number' && resultCount > 0)) {
    return 'missing_preview_metadata';
  }
  return resultCount === 0 ? 'known_zero_results' : 'missing_preview_metadata';
}

function limitPreviewResults<T>(results: T[], limit: number): T[] {
  return results.slice(0, Math.max(0, Math.floor(limit)));
}

export function buildWebSearchPreviewMetadata(
  results: WebSearchPreviewResult[],
  limit = DEFAULT_PARENT_PREVIEW_METADATA_LIMIT,
): { result_count: number; preview_results: WebSearchPreviewResult[] } {
  return {
    result_count: results.length,
    preview_results: limitPreviewResults(results, limit).map((result) => ({
      title: result.title,
      url: result.url,
      favicon: result.favicon,
      favicon_url: result.favicon_url,
      meta_url: result.meta_url,
      preview_image_url: result.preview_image_url,
      snippet: result.snippet,
    })),
  };
}

export function buildImageSearchPreviewMetadata(
  results: ImageSearchPreviewResult[],
  limit = DEFAULT_PARENT_PREVIEW_METADATA_LIMIT,
): { result_count: number; preview_results: ImageSearchPreviewResult[]; preview_results_json: string } {
  const previewResults = limitPreviewResults(results, limit).map((result) => ({
    title: result.title,
    source_page_url: result.source_page_url,
    image_url: result.image_url,
    thumbnail_url: result.thumbnail_url,
    source: result.source,
    favicon_url: result.favicon_url,
  }));

  return {
    result_count: results.length,
    preview_results: previewResults,
    preview_results_json: JSON.stringify(previewResults),
  };
}
