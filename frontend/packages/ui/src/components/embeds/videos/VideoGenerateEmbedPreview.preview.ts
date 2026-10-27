const defaultProps = {
  prompt: 'Sunrise over an alpine meadow',
  model: 'veo-3.1-fast-generate-preview',
  resolution: '720p',
  previewVideoUrl: '/store-examples/video-generate-1.mp4',
  previewImageUrl: '/store-examples/video-generate-1-poster.webp',
  id: 'preview-generated-video',
  status: 'finished' as const,
  onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  processing: { ...defaultProps, status: 'processing' as const, previewVideoUrl: '' },
  error: { ...defaultProps, status: 'error' as const, previewVideoUrl: '', error: 'Video generation failed' },
};
