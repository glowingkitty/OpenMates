/**
 * Preview of SlidesEditor against the real Rust core in the shared Worker (the
 * deck replica, every operation and undo/redo run there; no TypeScript deck model).
 * Needs a Rust-core build (VITE_OPENMATES_RUST_CORE=1 plus the wasm package), as on
 * app.dev; without it the editor shows its "editing is not available" state.
 * Access at: /dev/preview/embeds/slides/SlidesEditor?chrome=0
 * Phone: add `&width=390`.
 */
import { normalisedEditorDeck } from './slidesPreviewFixture';
import type { EditedDeck } from './slidesDeckVersion';

const defaultProps = {
  markup: normalisedEditorDeck,
  initialSlideId: 's2',
  onSave: async (deck: EditedDeck) => {
    console.info('[SlidesEditor preview] saved markup', deck.markup.length);
  },
  onExit: () => {}
};

export default defaultProps;

export const variants = {
  /** The heading of slide 2 selected: selection frame and text toolbar. */
  textSelected: { ...defaultProps, initialElementId: 'e3' },
  /** The ellipse selected (no text tools). */
  shapeSelected: { ...defaultProps, initialElementId: 'e5' },
  /** Title slide with layout-placed text (no own geometry). */
  titleSlide: { ...defaultProps, initialSlideId: 's1', initialElementId: 'e1' },
  /** Done after a change fails to save: the edits stay open with a retry. */
  saveFails: {
    ...defaultProps,
    onSave: async () => {
      throw new Error('preview: save refused');
    }
  },
  /** Not normalised markup: the core refuses to open it. */
  refused: { ...defaultProps, markup: '<deck><slide><text>Hi</text></slide></deck>' }
};
