/**
 * Preview mock data for SlideCanvas.
 * Access at: /dev/preview/embeds/slides/SlideCanvas
 */
import { parseSlidesMarkup } from './slidesMarkup';
import { hostileDeck, sampleDeck } from './slidesPreviewFixture';

function props(source: string, slideIndex = 1) {
  const result = parseSlidesMarkup(source);
  if (!('deck' in result)) throw new Error(`fixture deck does not parse: ${result.reason}`);
  const { deck } = result;
  return { slide: deck.slides[slideIndex] ?? deck.slides[0], width: deck.width, height: deck.height, template: deck.template, animated: false };
}

/** Default props: a 16:9 content slide */
const defaultProps = props(sampleDeck('16:9'));
export default defaultProps;

export const variants = {
  aspect16x10: props(sampleDeck('16:10')),
  aspect4x3: props(sampleDeck('4:3')),
  title: props(sampleDeck('16:9'), 0),
  twoColumn: props(sampleDeck('16:9'), 2),
  quote: props(sampleDeck('16:9'), 3),
  hostile: props(hostileDeck, 0)
};
