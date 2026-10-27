const defaultProps = {
  prompt: 'Sunrise over an alpine meadow',
  model: 'veo-3.1-fast-generate-preview',
  resolution: '720p',
  previewVideoUrl: '/store-examples/video-generate-1.mp4',
  previewImageUrl: '/store-examples/video-generate-1-poster.webp',
  onClose: () => {},
};
export default defaultProps;
export const variants = {
  loading: { ...defaultProps, previewVideoUrl: '' },
  withNavigation: { ...defaultProps, hasPreviousEmbed: true, hasNextEmbed: true, onNavigatePrevious: () => {}, onNavigateNext: () => {} },
};
