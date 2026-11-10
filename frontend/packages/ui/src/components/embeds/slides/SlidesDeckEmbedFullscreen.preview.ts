/**
 * Preview mock data for SlidesDeckEmbedFullscreen.
 * Access at: /dev/preview/embeds/slides/SlidesDeckEmbedFullscreen
 */
import { hostileDeck, normalisedEditorDeck, sampleDeck } from './slidesPreviewFixture';

function content(markup: string, title: string, aspect: string, slideCount: number) {
  return { decodedContent: { slides_markup: markup, title, slide_count: slideCount, aspect } };
}

const defaultProps = {
  data: content(sampleDeck('16:9'), 'Quarterly review', '16:9', 4),
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false
};

export default defaultProps;

export const variants = {
  aspect16x10: { ...defaultProps, data: content(sampleDeck('16:10'), 'Quarterly review', '16:10', 4) },
  aspect4x3: { ...defaultProps, data: content(sampleDeck('4:3'), 'Quarterly review', '4:3', 4) },
  withNavigation: { ...defaultProps, hasPreviousEmbed: true, hasNextEmbed: true, onNavigatePrevious: () => {}, onNavigateNext: () => {} },
  hostile: { ...defaultProps, data: content(hostileDeck, 'Hostile', '16:9', 1) },
  empty: { ...defaultProps, data: content('', '', '16:9', 0) },
  /**
   * Normalised markup the Rust core opens: Edit is available with the core build.
   * The preview embed is not in the local embed store, so Done after a change shows
   * the save-failed state (edits kept, retry); real saving is covered end to end.
   */
  editable: { ...defaultProps, embedId: 'preview-deck-embed', data: content(normalisedEditorDeck, 'Quarterly review', '16:9', 3) }
};
