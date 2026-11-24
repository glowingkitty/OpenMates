// figma-visual-proof: not-required. Original Design artboard.
import { mockup } from './editor/designExamples';

const onFullscreen = () => window.location.assign('/dev/preview/embeds/design/DesignDocumentEmbedFullscreen?chrome=0');
export default { id: 'design-preview', design: mockup, status: 'finished', onFullscreen } as const;
