/**
 * Preview mock data for SlideImageElement.
 * Access at: /dev/preview/embeds/slides/SlideImageElement
 * Resolved URLs are supplied directly (data: URLs), so no embed store is needed.
 */
const animatedSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">
  <rect width="400" height="300" fill="#eef"/>
  <circle cx="60" cy="150" r="40" fill="#e33">
    <animate attributeName="cx" values="60;340;60" dur="2s" repeatCount="indefinite"/>
  </circle>
</svg>`;

const stillPng =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

const resolved = {
  url: stillPng,
  animatedUrl: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(animatedSvg)}`
};

const defaultProps = { embedRef: 'preview-animated', alt: 'Animated chart', fit: 'contain' as const, motion: true, resolved };
export default defaultProps;

export const variants = {
  stillOnly: { ...defaultProps, motion: false },
  rasterOnly: { ...defaultProps, resolved: { url: stillPng } }
};
