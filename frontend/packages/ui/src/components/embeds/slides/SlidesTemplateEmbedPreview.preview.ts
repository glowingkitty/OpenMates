/**
 * Preview mock data for SlidesTemplateEmbedPreview.
 * Access at: /dev/preview/embeds/slides/SlidesTemplateEmbedPreview
 */
import { BUILTIN_SLIDES_TEMPLATES } from './slidesBuiltinTemplates.generated';

const themed = BUILTIN_SLIDES_TEMPLATES.find((template) => template.id !== 'builtin:plain') ?? BUILTIN_SLIDES_TEMPLATES[0];
const plain = BUILTIN_SLIDES_TEMPLATES.find((template) => template.id === 'builtin:plain') ?? BUILTIN_SLIDES_TEMPLATES[0];
const layoutCount = (markup: string) => (markup.match(/<slide\b/g) ?? []).length;

const defaultProps = {
  id: 'preview-slides-template-1',
  title: themed.name,
  slideCount: layoutCount(themed.markup),
  aspect: '16:9',
  slidesMarkup: themed.markup,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {}
};

export default defaultProps;

export const variants = {
  plain: { ...defaultProps, id: 'preview-slides-template-plain', title: plain.name, slideCount: layoutCount(plain.markup), slidesMarkup: plain.markup },
  processing: { id: 'preview-slides-template-processing', status: 'processing' as const, isMobile: false, onFullscreen: () => {} },
  error: { id: 'preview-slides-template-error', status: 'error' as const, isMobile: false, onFullscreen: () => {} },
  mobile: { ...defaultProps, id: 'preview-slides-template-mobile', isMobile: true }
};
