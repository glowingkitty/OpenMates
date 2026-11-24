/** Opens bounded raster child embeds through the authorized local embed reader. */
import { resolveEmbedForOpen } from '../../../../services/embedResolver';
import { getWorkspaceCacheEpoch } from '../../../../services/workspaceCacheLifecycle';

const MAX_ASSET_BASE64 = 512 * 1024;
const MAX_ASSET_PIXELS = 4 * 1024 * 1024;
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];

function isBoundedPng(bytes: Uint8Array): boolean {
  if (bytes.length < 33 || !PNG_SIGNATURE.every((byte, index) => byte === bytes[index])) return false;
  // Check the dimensions before the browser allocates a decoded bitmap.
  const header = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (header.getUint32(8) !== 13 || header.getUint32(12) !== 0x49484452) return false;
  const width = header.getUint32(16);
  const height = header.getUint32(20);
  return width > 0 && height > 0 && width <= 4096 && height <= 4096 && width * height <= MAX_ASSET_PIXELS;
}

export async function readDesignImage(assetId: string, embedId: string, chatId: string): Promise<ImageBitmap | null> {
  const epoch = getWorkspaceCacheEpoch();
  const row = await resolveEmbedForOpen(assetId, { chatId });
  if (getWorkspaceCacheEpoch() !== epoch || row?.parent_embed_id !== embedId ||
    row.type !== 'design-raster' || row.status !== 'finished' || typeof row.content !== 'string' ||
    row.content.length > MAX_ASSET_BASE64 + 128) return null;

  const data: { dataBase64?: unknown } | null = JSON.parse(row.content);
  if (typeof data?.dataBase64 !== 'string' || data.dataBase64.length > MAX_ASSET_BASE64) return null;

  const bytes = Uint8Array.from(atob(data.dataBase64), (character) => character.charCodeAt(0));
  try {
    if (!isBoundedPng(bytes) || getWorkspaceCacheEpoch() !== epoch) return null;
    const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
    if (getWorkspaceCacheEpoch() !== epoch || bitmap.width * bitmap.height > MAX_ASSET_PIXELS) {
      bitmap.close();
      return null;
    }
    return bitmap;
  } finally {
    bytes.fill(0);
  }
}
