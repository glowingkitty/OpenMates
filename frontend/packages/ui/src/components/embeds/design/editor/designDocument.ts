// Preview-only document values. Array order is back to front.
export type DesignFont = 'Sans' | 'Serif' | 'Mono';

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
}

interface LayerBase extends Box {
  id: string;
  name: string;
  hidden?: boolean;
  locked?: boolean;
}

export type DesignLayer = LayerBase & (
  | { kind: 'shape'; shape: 'rectangle' | 'ellipse'; color: string; radius?: number }
  | { kind: 'text'; text: string; font: DesignFont; fontSize: number; weight: number; color: string }
  | { kind: 'image'; src: string }
  | { kind: 'path'; path: string; viewWidth: number; viewHeight: number; color: string }
);

export interface DesignPage {
  id: string;
  name: string;
  width: number;
  height: number;
  background: string;
  layers: DesignLayer[];
}

export interface DesignDocument {
  title: string;
  pages: DesignPage[];
}

// Stress fixtures can exceed the provisional cap to measure the headroom.
export const PREVIEW_LAYER_CAP = 250;
export const MIN_LAYER_SIZE = 8;
export const designFonts: Record<DesignFont, string> = {
  Sans: 'Arial, sans-serif',
  Serif: 'Georgia, serif',
  Mono: 'monospace'
};

export interface Point { x: number; y: number }

export function rotate(point: Point, degrees: number): Point {
  const angle = degrees * Math.PI / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return { x: point.x * cos - point.y * sin, y: point.x * sin + point.y * cos };
}

export function center(box: Box): Point {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

export function insideLayer(layer: DesignLayer, point: Point, pathHit: (layer: DesignLayer, point: Point) => boolean) {
  const origin = center(layer);
  const local = rotate({ x: point.x - origin.x, y: point.y - origin.y }, -layer.rotation);
  const u = local.x / layer.width + 0.5;
  const v = local.y / layer.height + 0.5;
  if (u < 0 || u > 1 || v < 0 || v > 1) return false;
  if (layer.kind === 'shape' && layer.shape === 'ellipse') return Math.hypot(u - 0.5, v - 0.5) <= 0.5;
  if (layer.kind === 'path') return pathHit(layer, { x: u * layer.viewWidth, y: v * layer.viewHeight });
  return true;
}

export function resizeFromCorner(box: Box, delta: Point, corner: Point): Box {
  const local = rotate(delta, -box.rotation);
  const width = Math.max(MIN_LAYER_SIZE, box.width + local.x * corner.x);
  const height = Math.max(MIN_LAYER_SIZE, box.height + local.y * corner.y);
  const shift = rotate({
    x: (width - box.width) * corner.x / 2,
    y: (height - box.height) * corner.y / 2
  }, box.rotation);
  const origin = center(box);
  return { ...box, width, height, x: origin.x + shift.x - width / 2, y: origin.y + shift.y - height / 2 };
}
