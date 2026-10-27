const defaultProps = {
  id: 'preview-model-catalog', title: 'Low-poly research observatory', provider: 'Example Catalogue',
  creatorName: 'Example Artist', license: 'CC BY 4.0', filesCount: 3, isFree: true,
  sourcePageUrl: 'https://example.com/models/observatory',
  previewImageUrl: '/store-examples/generate-2.webp',
  presentationOnly: true, onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  missingData: { ...defaultProps, creatorName: '', license: '', filesCount: null, isFree: null, previewImageUrl: '' },
  longTitle: { ...defaultProps, title: 'An exceptionally detailed low-poly research observatory for community science education' },
  chat: { ...defaultProps, resultContext: 'chat' as const },
  brokenImage: { ...defaultProps, previewImageUrl: 'data:image/png;base64,invalid' },
};
