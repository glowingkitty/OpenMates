// frontend/packages/ui/src/components/embeds/embedPreviewHydration.ts
// Pure helpers for keeping embed preview hydration bounded.
// Components use these helpers to avoid resolving hidden carousel slides during
// initial chat render. Parent previews must remain self-contained and must not
// hydrate child embeds as a fallback.
// Covered by embedPreviewHydration.test.ts.

export const DEFAULT_CAROUSEL_HYDRATION_OVERSCAN = 1;

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
