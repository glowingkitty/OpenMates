/** Local upload preparation. Cleanup never prevents the user's upload. */
import { stripImageMetadata } from './images.js';
import { stripAudioMetadata } from './audio.js';

export interface SanitizedUpload {
  bytes: Uint8Array;
  mimeType: string;
  filename: string;
  status: 'sanitized' | 'unsupported' | 'failed';
}

const EXTENSIONS: Record<string, string> = {
  'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
  'image/gif': 'gif', 'image/svg+xml': 'svg', 'image/bmp': 'bmp',
  'image/tiff': 'tiff', 'image/heic': 'heic', 'image/heif': 'heif',
  'application/pdf': 'pdf', 'audio/mpeg': 'mp3', 'audio/aac': 'aac',
  'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/mp4': 'm4a',
  'audio/webm': 'webm', 'audio/ogg': 'ogg',
};

function detectMimeType(bytes: Uint8Array, declaredType: string, filename: string): string {
  const startsWith = (...values: number[]) => values.every((value, index) => bytes[index] === value);
  const ascii = (start: number, end: number) => String.fromCharCode(...bytes.subarray(start, end));
  if (startsWith(0xff, 0xd8)) return 'image/jpeg';
  if (startsWith(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return 'image/png';
  if (ascii(0, 4) === 'RIFF') {
    if (ascii(8, 12) === 'WEBP') return 'image/webp';
    if (ascii(8, 12) === 'WAVE') return 'audio/wav';
  }
  if (/^GIF8[79]a$/.test(ascii(0, 6))) return 'image/gif';
  if (ascii(0, 2) === 'BM') return 'image/bmp';
  if (startsWith(0x49, 0x49, 0x2a, 0) || startsWith(0x4d, 0x4d, 0, 0x2a)) return 'image/tiff';
  if (ascii(0, 5) === '%PDF-') return 'application/pdf';
  if (ascii(0, 4) === 'OggS') return 'audio/ogg';
  if (ascii(0, 3) === 'ID3') return declaredType === 'audio/aac' ? 'audio/aac' : 'audio/mpeg';
  if (startsWith(0x1a, 0x45, 0xdf, 0xa3)) return 'audio/webm';
  if (ascii(4, 8) === 'ftyp') {
    const brand = ascii(8, 12);
    if (/^(hei[cfx]|mif1|msf1)$/.test(brand)) return 'image/heic';
    return 'audio/mp4';
  }
  const extension = filename.match(/\.([a-zA-Z0-9]+)$/)?.[1].toLowerCase();
  if (!declaredType || declaredType === 'application/octet-stream') {
    const type = Object.entries(EXTENSIONS).find(([, value]) => value === extension)?.[0];
    if (type) return type;
    if (extension === 'jpeg') return 'image/jpeg';
    if (extension === 'tif') return 'image/tiff';
    if (extension === 'mp4') return 'audio/mp4';
    if (extension === 'oga') return 'audio/ogg';
  }
  return declaredType;
}

export async function sanitizeUploadBytes(
  bytes: Uint8Array,
  mimeType: string,
  filename: string,
): Promise<SanitizedUpload> {
  const baseType = detectMimeType(bytes, mimeType.split(';', 1)[0].toLowerCase(), filename);
  const result: SanitizedUpload = {
    bytes,
    mimeType: baseType || mimeType,
    filename,
    status: 'unsupported',
  };
  try {
    // Pass a copy: a partially failed rewrite must never damage the fallback.
    const input = new Uint8Array(bytes);
    let cleaned = stripImageMetadata(input, baseType) ?? stripAudioMetadata(input, baseType);
    if (!cleaned && !baseType.startsWith('image/') && !baseType.startsWith('audio/')) {
      const { stripDocumentMetadata } = await import('./documents.js');
      cleaned = await stripDocumentMetadata(input, baseType, filename);
    }
    if (cleaned) {
      if (!cleaned.byteLength) throw new Error('Empty sanitized upload');
      // A rewrite must not turn an accepted-size file into a rejected upload.
      if (cleaned.byteLength > 100 * 1024 * 1024 && cleaned.byteLength > bytes.byteLength) {
        throw new Error('Sanitized upload exceeds the upload size limit');
      }
      result.bytes = cleaned;
      result.status = 'sanitized';
    }
  } catch {
    // Do not log parser errors: these may contain private file data or properties.
    result.status = 'failed';
  }
  return result;
}
