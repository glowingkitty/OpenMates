const defaultProps = {
  title: 'A clear result title',
  description: 'A concise description of the source and the information available in this result.',
  sourceLabel: 'example.org',
  faviconUrl: '/favicon.png',
  imageUrl: '/store-examples/events-1.webp',
  imageAlt: 'Event illustration',
};
export default defaultProps;
export const variants = {
  noImage: { ...defaultProps, imageUrl: undefined },
  brokenImage: { ...defaultProps, imageUrl: '/missing-result-preview-image.webp' },
  contain: { ...defaultProps, mediaFit: 'contain' },
  textFirst: { ...defaultProps, textFirst: true },
  longTitle: { ...defaultProps, title: 'A deliberately long title to verify wrapping, bounded card text and responsive content across narrow and wide containers' },
};
