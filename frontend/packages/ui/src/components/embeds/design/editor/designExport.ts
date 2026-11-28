// figma-visual-proof: not-required. Encodes the validated scene. Browser file and pixel tests cover the outputs.
/** Local file encoders for approved artboards and their decoded image layers. */
import { jsPDF } from 'jspdf';
import { designFonts, type DesignDocument, type DesignLayer, type DesignPage } from './designDocument';
import { drawDesignPage, imageLayerKey, type DecodedImages } from './designRenderer';
import { designFont, designTextLines } from './designText';

const SVG_NS = 'http://www.w3.org/2000/svg';
const XLINK_NS = 'http://www.w3.org/1999/xlink';
const MAX_PDF_PIXELS = 32 * 1024 * 1024;
const MAX_IMAGE_PIXELS = 16 * 1024 * 1024;
export type DesignExportFormat = 'svg' | 'png' | 'pdf';
interface PageImages {
  readAsset?: (assetId: string) => Promise<ImageBitmap | null>;
  previewImages?: DecodedImages;
}

export class DesignExportImageError extends Error {}

async function withPageImages<T>(page: DesignPage, source: PageImages, write: (images: DecodedImages) => T): Promise<T> {
  const images = new Map(source.previewImages);
  const owned: ImageBitmap[] = [];
  let pixels = 0;
  try {
    for (const layer of page.layers) {
      if (layer.kind !== 'image' || layer.hidden) continue;
      const key = imageLayerKey(layer);
      if (images.get(key)) continue;
      const bitmap = layer.assetId && source.readAsset ? await source.readAsset(layer.assetId) : null;
      if (!bitmap) throw new DesignExportImageError('The image is unavailable on this device.');
      owned.push(bitmap);
      pixels += bitmap.width * bitmap.height;
      if (pixels > MAX_IMAGE_PIXELS) throw new DesignExportImageError('The page exceeds the image decoding limit.');
      images.set(key, bitmap);
    }
    return write(images);
  } finally {
    for (const bitmap of owned) bitmap.close();
  }
}

function canvasAt(width: number, height: number): CanvasRenderingContext2D {
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(width);
  canvas.height = Math.ceil(height);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('The browser could not create an export surface.');
  return context;
}

function pageRaster(page: DesignPage, source: PageImages, scale = 1): Promise<HTMLCanvasElement> {
  return withPageImages(page, source, (images) => {
    const context = canvasAt(page.width * scale, page.height * scale);
    context.scale(context.canvas.width / page.width, context.canvas.height / page.height);
    drawDesignPage(context, page, images);
    return context.canvas;
  });
}

function pngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (blob) resolve(blob);
    else reject(new Error('The browser could not create a PNG.'));
  }, 'image/png'));
}

function svgNode(parent: Element | null, name: string, attributes: Record<string, string | number>): SVGElement {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  parent?.appendChild(node);
  return node;
}

function appendSvgImage(node: SVGElement, definition: SVGElement, assets: Map<string, string>,
  layer: Extract<DesignLayer, { kind: 'image' }>, image: HTMLImageElement | ImageBitmap) {
  const key = imageLayerKey(layer);
  const imageWidth = 'naturalWidth' in image ? image.naturalWidth : image.width;
  const imageHeight = 'naturalHeight' in image ? image.naturalHeight : image.height;
  let id = assets.get(key);
  if (!id) {
    id = `design-image-${assets.size}`;
    assets.set(key, id);
    const surface = canvasAt(imageWidth, imageHeight);
    surface.drawImage(image, 0, 0);
    try {
      svgNode(definition, 'image', { id, width: imageWidth, height: imageHeight })
        .setAttributeNS(XLINK_NS, 'xlink:href', surface.canvas.toDataURL('image/png'));
    } finally {
      surface.canvas.width = 0;
    }
  }
  const viewport = svgNode(node, 'svg', { width: layer.width, height: layer.height, overflow: 'hidden',
    viewBox: `0 0 ${imageWidth} ${imageHeight}`, preserveAspectRatio: 'xMidYMid slice' });
  svgNode(viewport, 'use', {}).setAttributeNS(XLINK_NS, 'xlink:href', `#${id}`);
}

function svgPage(page: DesignPage, images: DecodedImages): Blob {
  const svg = svgNode(null, 'svg', { width: page.width, height: page.height, viewBox: `0 0 ${page.width} ${page.height}` });
  const assets = new Map<string, string>();
  const definitions = svgNode(svg, 'defs', {});
  const bounds = svgNode(definitions, 'clipPath', { id: 'artboard' });
  svgNode(bounds, 'rect', { width: page.width, height: page.height });
  const paint = svgNode(svg, 'g', { 'clip-path': 'url(#artboard)' });
  svgNode(paint, 'rect', { width: page.width, height: page.height, fill: page.background });
  const measure = canvasAt(1, 1);
  for (const [index, layer] of page.layers.entries()) {
    if (layer.hidden) continue;
    const { x, y, width, height, rotation } = layer;
    const node = svgNode(paint, 'g', { transform: `translate(${x} ${y}) rotate(${rotation} ${width / 2} ${height / 2})` });
    if (layer.kind === 'shape' && layer.shape === 'ellipse') {
      svgNode(node, 'ellipse', { cx: width / 2, cy: height / 2, rx: width / 2, ry: height / 2, fill: layer.color });
    } else if (layer.kind === 'shape') {
      svgNode(node, 'rect', { width, height, rx: Math.min(layer.radius ?? 0, width / 2, height / 2), fill: layer.color });
    } else if (layer.kind === 'path') {
      svgNode(node, 'path', { d: layer.path, fill: layer.color, transform: `scale(${width / layer.viewWidth} ${height / layer.viewHeight})` });
    } else if (layer.kind === 'image') {
      const image = images.get(imageLayerKey(layer));
      if (!image) throw new DesignExportImageError('The image is unavailable on this device.');
      appendSvgImage(node, definitions, assets, layer, image);
    } else {
      appendSvgText(node, layer, index, measure);
    }
  }
  return new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' });
}

function appendSvgText(node: SVGElement, layer: Extract<DesignLayer, { kind: 'text' }>, index: number, measure: CanvasRenderingContext2D) {
  const clip = `design-text-${index}`;
  const clipPath = svgNode(node, 'clipPath', { id: clip });
  svgNode(clipPath, 'rect', { width: layer.width, height: layer.height });
  const text = svgNode(node, 'text', {
    fill: layer.color, 'font-family': designFonts[layer.font], 'font-size': layer.fontSize,
    'font-weight': layer.weight, 'clip-path': `url(#${clip})`,
  });
  measure.font = designFont(layer);
  for (const line of designTextLines(layer, (value) => measure.measureText(value).width)) {
    svgNode(text, 'tspan', { x: 0, y: line.baseline, 'white-space': 'pre' }).textContent = line.text;
  }
}

async function pdfPages(design: DesignDocument, source: PageImages, signal: AbortSignal): Promise<Blob> {
  // Keep the working raster and document payload bounded on phones. The physical
  // size of each PDF page remains tied to the original artboard.
  const pixels = design.pages.reduce((total, page) => total + page.width * page.height, 0);
  const scale = Math.min(1, Math.sqrt(MAX_PDF_PIXELS / pixels));
  const format = (page: DesignPage): [number, number] => [page.width * 0.75, page.height * 0.75];
  const orientation = (page: DesignPage) => page.width > page.height ? 'landscape' as const : 'portrait' as const;
  const first = design.pages[0];
  const pdf = new jsPDF({ unit: 'pt', format: format(first), orientation: orientation(first), compress: true });
  pdf.setProperties({ title: design.title });
  for (const [index, page] of design.pages.entries()) {
    signal.throwIfAborted();
    if (index) pdf.addPage(format(page), orientation(page));
    const canvas = await pageRaster(page, source, scale);
    try {
      const [width, height] = format(page);
      pdf.addImage(canvas, 'PNG', 0, 0, width, height, `artboard-${index}`, 'FAST');
    } finally {
      canvas.width = 0;
    }
  }
  return pdf.output('blob');
}

export async function exportDesign(format: DesignExportFormat, design: DesignDocument, activePage: DesignPage,
  source: PageImages, signal: AbortSignal): Promise<Blob> {
  if (format === 'svg') return withPageImages(activePage, source, (images) => svgPage(activePage, images));
  if (format === 'pdf') return pdfPages(design, source, signal);
  const canvas = await pageRaster(activePage, source);
  try {
    return await pngBlob(canvas);
  } finally {
    canvas.width = 0;
  }
}
