/**
 * Preview mock data for SlidesTemplateEmbedFullscreen.
 * Access at: /dev/preview/embeds/slides/SlidesTemplateEmbedFullscreen
 */
import { BUILTIN_SLIDES_TEMPLATES } from './slidesBuiltinTemplates.generated';

function content(markup: string, title: string) {
  return {
    decodedContent: { slides_markup: markup, title, slide_count: (markup.match(/<slide\b/g) ?? []).length, aspect: '16:9' }
  };
}

const themed = BUILTIN_SLIDES_TEMPLATES.find((template) => template.id !== 'builtin:plain') ?? BUILTIN_SLIDES_TEMPLATES[0];
const plain = BUILTIN_SLIDES_TEMPLATES.find((template) => template.id === 'builtin:plain') ?? BUILTIN_SLIDES_TEMPLATES[0];

const defaultProps = {
  data: content(themed.markup, themed.name),
  embedId: 'preview-slides-template-embed',
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false
};

export default defaultProps;

export const variants = {
  plain: { ...defaultProps, data: content(plain.markup, plain.name) },
  withNavigation: { ...defaultProps, hasPreviousEmbed: true, hasNextEmbed: true, onNavigatePrevious: () => {}, onNavigateNext: () => {} },
  empty: { ...defaultProps, data: content('', '') }
};
