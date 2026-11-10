/**
 * Picks the stored file a generated-image card shows.
 *
 * Previews made before the preview kept the whole picture were centre-cropped
 * to exactly 600x400. Such a card loads the uncropped file instead, so an older
 * picture is never shown cut off.
 */

export interface StoredImageFile {
  s3_key: string;
  width?: number;
  height?: number;
  format?: string;
  aes_nonce?: string;
  encryption?: string;
}

export interface StoredImageFiles {
  preview?: StoredImageFile;
  full?: StoredImageFile;
  original?: StoredImageFile;
}

const LEGACY_CROP_WIDTH = 600;
const LEGACY_CROP_HEIGHT = 400;
const LEGACY_CROP_RATIO = LEGACY_CROP_WIDTH / LEGACY_CROP_HEIGHT;
const RATIO_TOLERANCE = 0.02;

function isLegacyCrop(preview: StoredImageFile): boolean {
  return preview.width === LEGACY_CROP_WIDTH && preview.height === LEGACY_CROP_HEIGHT;
}

function hasOtherRatio(file: StoredImageFile): boolean {
  if (!file.width || !file.height) return false;
  return Math.abs(file.width / file.height - LEGACY_CROP_RATIO) > RATIO_TOLERANCE;
}

/** The file the card shows: the preview, or the uncropped source of a legacy cropped preview. */
export function cardImageFile(files: StoredImageFiles | undefined): StoredImageFile | undefined {
  const preview = files?.preview;
  if (!preview?.s3_key || !isLegacyCrop(preview)) return preview;
  const original = files?.original;
  // A vector original has no reliable pixel size; it always holds the whole picture.
  if (original?.s3_key && original.format === 'svg') return original;
  const full = files?.full;
  if (full?.s3_key && hasOtherRatio(full)) return full;
  return preview;
}
