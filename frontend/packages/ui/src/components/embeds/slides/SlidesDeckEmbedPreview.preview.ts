/**
 * Preview mock data for SlidesDeckEmbedPreview.
 * Access at: /dev/preview/embeds/slides/SlidesDeckEmbedPreview
 */
import { hostileDeck, sampleDeck } from './slidesPreviewFixture';

const defaultProps = {
  id: 'preview-slides-1',
  title: 'Quarterly review',
  slideCount: 4,
  aspect: '16:9',
  slidesMarkup: sampleDeck('16:9'),
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {}
};

export default defaultProps;

export const variants = {
  aspect16x10: { ...defaultProps, id: 'preview-slides-16-10', aspect: '16:10', slidesMarkup: sampleDeck('16:10') },
  aspect4x3: { ...defaultProps, id: 'preview-slides-4-3', aspect: '4:3', slidesMarkup: sampleDeck('4:3') },
  /** Only the slides completed so far are shown while streaming */
  streaming: {
    ...defaultProps,
    id: 'preview-slides-streaming',
    status: 'processing' as const,
    slidesMarkup: sampleDeck('16:9').split('<slide id="s3"')[0]
  },
  processing: { id: 'preview-slides-processing', status: 'processing' as const, isMobile: false, onFullscreen: () => {} },
  error: { id: 'preview-slides-error', status: 'error' as const, isMobile: false, onFullscreen: () => {} },
  hostile: { ...defaultProps, id: 'preview-slides-hostile', title: 'Hostile', slidesMarkup: hostileDeck },
  mobile: { ...defaultProps, id: 'preview-slides-mobile', isMobile: true }
};
