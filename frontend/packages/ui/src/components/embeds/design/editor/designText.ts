// figma-visual-proof: not-required. Shares the existing Canvas line layout with SVG.
/** Shared text layout for Canvas and SVG. */
import { designFonts, type DesignLayer } from './designDocument';

export type TextLayer = Extract<DesignLayer, { kind: 'text' }>;

export function designFont(layer: TextLayer): string {
  return `${layer.weight} ${layer.fontSize}px ${designFonts[layer.font]}`;
}

export function* designTextLines(layer: TextLayer, measure: (text: string) => number) {
  const { width, height, fontSize } = layer;
  const step = fontSize * 1.13;
  let baseline = fontSize;
  for (const paragraph of layer.text.split('\n')) {
    let line = '';
    for (const word of paragraph.split(' ')) {
      const combined = line ? `${line} ${word}` : word;
      if (line && measure(combined) > width) {
        yield { text: line, baseline };
        baseline += step;
        if (baseline - fontSize >= height) return;
        line = word;
      } else {
        line = combined;
      }
    }
    yield { text: line, baseline };
    baseline += step;
    if (baseline - fontSize >= height) return;
  }
}
