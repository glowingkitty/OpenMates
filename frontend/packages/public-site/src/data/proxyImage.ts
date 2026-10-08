const PREVIEW_BASE = 'https://preview.openmates.org';

/** Keep external image requests behind the shared first-party preview proxy. */
export function proxyImage(url: string | null | undefined, maxWidth?: number): string {
  if (!url) return '';
  if (url.startsWith('/') || url.startsWith('data:') || url.startsWith(`${PREVIEW_BASE}/api/v1/image`)) return url;
  const params = new URLSearchParams({ url });
  if (maxWidth !== undefined) params.set('max_width', String(maxWidth));
  return `${PREVIEW_BASE}/api/v1/image?${params}`;
}
