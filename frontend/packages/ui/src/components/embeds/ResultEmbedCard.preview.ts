const defaultProps = {
  title: 'A clear result title',
  description: 'A concise description of the source and the information available in this result.',
  sourceLabel: 'example.org',
  faviconUrl: '/favicon.png',
  imageUrl: '/store-examples/events-1.webp',
  imageAlt: 'Event illustration',
};
/** Synthetic, self-contained images with a visible border so cropping is detectable. */
function syntheticImage(width: number, height: number, fill: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="${fill}"/><rect x="6" y="6" width="${width - 12}" height="${height - 12}" fill="none" stroke="#ffffff" stroke-width="12"/><circle cx="${width / 2}" cy="${height / 2}" r="${Math.min(width, height) / 4}" fill="#ffffff"/></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
const twoLineTitle = 'Conference title long enough to need two full lines in a compact card';
export default defaultProps;
export const variants = {
  noImage: { ...defaultProps, imageUrl: undefined },
  squareLogo: { ...defaultProps, title: twoLineTitle, imageUrl: syntheticImage(400, 400, '#2563eb') },
  wideBanner: { ...defaultProps, title: twoLineTitle, imageUrl: syntheticImage(1200, 300, '#16a34a') },
  tallPoster: { ...defaultProps, title: twoLineTitle, imageUrl: syntheticImage(300, 900, '#9333ea') },
  brokenImage: { ...defaultProps, title: twoLineTitle, imageUrl: 'data:image/png;base64,broken' },
  contain: { ...defaultProps, mediaFit: 'contain' },
  textFirst: { ...defaultProps, textFirst: true },
  longTitle: { ...defaultProps, title: 'A deliberately long title to verify wrapping, bounded card text and responsive content across narrow and wide containers' },
};
