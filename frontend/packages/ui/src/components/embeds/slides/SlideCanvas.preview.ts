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

/** Notepad with a body, a visible to-do and a hidden notepad and to-do (not rendered). */
const interactiveDeck = `<deck title="Interactive" aspect="16:9" template="builtin:plain">
  <slide id="s1">
    <notepad id="e1" x="80" y="80" w="860" h="260" title="Ideas">Line one
Line two</notepad>
    <todo id="e2" x="1000" y="80" w="800" h="240" title="Next"><item done="true">Visible item</item></todo>
    <notepad id="e3" x="80" y="400" w="860" h="260" title="Secret" hidden="true">Hidden body</notepad>
    <todo id="e4" x="1000" y="400" w="800" h="240" title="Private" hidden="true"><item done="false">Hidden item</item></todo>
  </slide>
</deck>
`;

/** Default props: a 16:9 content slide */
const defaultProps = props(sampleDeck('16:9'));
export default defaultProps;

export const variants = {
  aspect16x10: props(sampleDeck('16:10')),
  aspect4x3: props(sampleDeck('4:3')),
  title: props(sampleDeck('16:9'), 0),
  twoColumn: props(sampleDeck('16:9'), 2),
  quote: props(sampleDeck('16:9'), 3),
  hostile: props(hostileDeck, 0),
  interactive: props(interactiveDeck, 0)
};
