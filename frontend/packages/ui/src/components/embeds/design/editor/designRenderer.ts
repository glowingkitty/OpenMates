import { registerWorkspaceCacheClear } from '../../../../services/workspaceCacheLifecycle';
import { designFonts, type DesignLayer, type DesignPage } from './designDocument';

export type DecodedImages = ReadonlyMap<string, HTMLImageElement | ImageBitmap | null>;
type Context = CanvasRenderingContext2D;
const paths = new Map<string, Path2D>();
registerWorkspaceCacheClear(() => paths.clear());

export function designPath(value: string): Path2D {
  let path = paths.get(value);
  if (!path) {
    path = new Path2D(value);
    if (paths.size >= 512) {
      const oldest = paths.keys().next().value;
      if (oldest !== undefined) paths.delete(oldest);
    }
    paths.set(value, path);
  }
  return path;
}

export function imageLayerKey(layer: Extract<DesignLayer, { kind: 'image' }>): string {
  return layer.assetId ?? layer.src;
}

export async function decodeImages(layers: DesignLayer[], existing: DecodedImages = new Map()): Promise<DecodedImages> {
  const sources = new Set(layers.flatMap((layer) => layer.kind === 'image' && !layer.assetId && layer.src ? [layer.src] : []));
  return new Map(await Promise.all([...sources].map(async (source) => {
    if (existing.has(source)) return [source, existing.get(source) ?? null] as const;
    const image = new Image();
    image.src = source;
    try {
      await image.decode();
      return [source, image] as const;
    } catch {
      return [source, null] as const;
    }
  })));
}

function drawText(ctx: Context, layer: Extract<DesignLayer, { kind: 'text' }>) {
  const { width, height, fontSize } = layer;
  ctx.beginPath();
  ctx.rect(0, 0, width, height);
  ctx.clip();
  ctx.font = `${layer.weight} ${fontSize}px ${designFonts[layer.font]}`;
  ctx.textBaseline = 'alphabetic';
  let y = fontSize;
  for (const paragraph of layer.text.split('\n')) {
    let line = '';
    for (const word of paragraph.split(' ')) {
      const next = line ? `${line} ${word}` : word;
      if (line && ctx.measureText(next).width > width) {
        ctx.fillText(line, 0, y);
        y += fontSize * 1.13;
        if (y - fontSize >= height) return;
        line = word;
      } else {
        line = next;
      }
    }
    ctx.fillText(line, 0, y);
    y += fontSize * 1.13;
    if (y - fontSize >= height) return;
  }
}

function drawLayer(ctx: Context, layer: DesignLayer, images: DecodedImages) {
  const { x, y, width, height, rotation } = layer;
  ctx.save();
  if (rotation) {
    ctx.translate(x + width / 2, y + height / 2);
    ctx.rotate(rotation * Math.PI / 180);
    ctx.translate(-width / 2, -height / 2);
  } else {
    ctx.translate(x, y);
  }
  if (layer.kind !== 'image') ctx.fillStyle = layer.color;
  switch (layer.kind) {
    case 'shape':
      if (layer.shape === 'ellipse') {
        ctx.beginPath();
        ctx.ellipse(width / 2, height / 2, width / 2, height / 2, 0, 0, Math.PI * 2);
        ctx.fill();
      } else if (layer.radius) {
        ctx.beginPath();
        ctx.roundRect(0, 0, width, height, Math.min(layer.radius, width / 2, height / 2));
        ctx.fill();
      } else {
        ctx.fillRect(0, 0, width, height);
      }
      break;
    case 'text':
      drawText(ctx, layer);
      break;
    case 'path':
      ctx.scale(width / layer.viewWidth, height / layer.viewHeight);
      ctx.fill(designPath(layer.path));
      break;
    case 'image': {
      const image = images.get(imageLayerKey(layer));
      if (!image) {
        ctx.fillStyle = '#d6d3cc';
        ctx.fillRect(0, 0, width, height);
        break;
      }
      const naturalWidth = 'naturalWidth' in image ? image.naturalWidth : image.width;
      const naturalHeight = 'naturalHeight' in image ? image.naturalHeight : image.height;
      const scale = Math.max(width / naturalWidth, height / naturalHeight);
      const sourceWidth = width / scale;
      const sourceHeight = height / scale;
      ctx.drawImage(image, (naturalWidth - sourceWidth) / 2, (naturalHeight - sourceHeight) / 2,
        sourceWidth, sourceHeight, 0, 0, width, height);
      break;
    }
  }
  ctx.restore();
}

/** Paint only the supplied page. Thumbnails reuse the same drawing at small resolution. */
export function drawDesignPage(ctx: Context, page: DesignPage, images: DecodedImages, draft?: DesignLayer | null) {
  ctx.save();
  ctx.fillStyle = page.background;
  ctx.fillRect(0, 0, page.width, page.height);
  ctx.beginPath();
  ctx.rect(0, 0, page.width, page.height);
  ctx.clip();
  for (const original of page.layers) {
    if (!original.hidden) drawLayer(ctx, draft?.id === original.id ? draft : original, images);
  }
  ctx.restore();
}
