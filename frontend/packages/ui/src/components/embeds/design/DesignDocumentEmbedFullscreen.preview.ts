// figma-visual-proof: not-required. Original Design artboards.
import { mockup } from './editor/designExamples';

export const layout = 'fill';
const document = {
  schemaVersion: 1,
  title: mockup.title,
  pages: mockup.pages.map((page) => ({
    ...page,
    layers: page.layers.map((layer) => layer.kind === 'path'
      ? { ...layer, path: 'M 0 67 C 17 67 20 18 40 18 C 60 18 64 75 80 75 Q 91 75 100 35 L 100 100 L 0 100 Z' }
      : layer)
  }))
};

const onClose = () => window.location.assign('/dev/preview');
export default { data: { decodedContent: document }, onClose };
export const variants = {
  unsupported: { data: { decodedContent: { ...document, schemaVersion: 12 } }, onClose }
};
