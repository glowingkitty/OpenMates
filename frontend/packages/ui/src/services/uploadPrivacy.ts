import { sanitizeUploadBytes } from '@repo/upload-privacy';

const BROWSER_REENCODE_TYPES = new Set(['image/bmp', 'image/heic', 'image/heif']);

async function tryReencodeImage(file: File): Promise<File | null> {
  if (!BROWSER_REENCODE_TYPES.has(file.type.toLowerCase()) || typeof Image === 'undefined') return null;
  let objectUrl: string | null = null;
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Image decode timed out')), 10_000);
      image.onload = () => { clearTimeout(timer); resolve(); };
      image.onerror = () => { clearTimeout(timer); reject(new Error('Could not decode image')); };
      objectUrl = URL.createObjectURL(file);
      image.src = objectUrl;
    });
    if (!image.naturalWidth || !image.naturalHeight) return null;
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d');
    if (!context) return null;
    context.drawImage(image, 0, 0);
    const blob = await new Promise<Blob | null>((resolve) => {
      const timer = setTimeout(() => resolve(null), 10_000);
      canvas.toBlob((value) => {
        clearTimeout(timer);
        resolve(value);
      }, 'image/png');
    });
    return blob && blob.size <= 100 * 1024 * 1024
      ? new File([blob], file.name, { type: 'image/png' }) : null;
  } catch {
    return null;
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

/** Prepare a browser file at the network boundary, retaining the bytes if privacy cleanup fails. */
export async function prepareFileForUpload(file: File): Promise<File> {
  let originalBytes: Uint8Array;
  try {
    originalBytes = new Uint8Array(await file.arrayBuffer());
  } catch {
    console.warn('[UploadPrivacy] Metadata cleanup failed; continuing upload.');
    return new File([file.slice(0, file.size, file.type)], file.name, { type: file.type });
  }
  try {
    const result = await sanitizeUploadBytes(originalBytes, file.type, file.name);
    if (result.status === 'failed') {
      console.warn('[UploadPrivacy] Metadata cleanup failed; continuing upload.');
    }
    if (result.status === 'unsupported') {
      const reencoded = await tryReencodeImage(file);
      if (reencoded) return reencoded;
      console.warn('[UploadPrivacy] Metadata cleanup unavailable for this format; continuing upload.');
    }
    return new File([new Uint8Array(result.bytes)], file.name, {
      type: result.mimeType || file.type,
    });
  } catch {
    console.warn('[UploadPrivacy] Metadata cleanup failed; continuing upload.');
    return new File([new Uint8Array(originalBytes)], file.name, { type: file.type });
  }
}
