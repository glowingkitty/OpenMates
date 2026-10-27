/** Normalize provider galleries and TOON pipe-delimited array scalars. */
export function normalizeShoppingProductImages(images: unknown, primary?: unknown): string[] {
  const supplied = Array.isArray(images) ? images : typeof images === 'string' ? images.split('|') : [];
  const values = supplied.filter((value): value is string => typeof value === 'string')
    .map((value) => value.trim()).filter(Boolean);
  // Preserve supplied gallery order; older results may contain only image_url.
  const fallback = typeof primary === 'string' ? primary.trim() : '';
  if (fallback && !values.includes(fallback)) values.unshift(fallback);
  return [...new Set(values)];
}
