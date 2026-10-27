/** Image-file actions for assistant embed nodes and references. */
import { resolveEmbed, decodeToonContent } from '../../../services/embedResolver';
import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
import { getWorkspaceCacheEpoch } from '../../../services/workspaceCacheLifecycle';
import { proxyImage } from '../../../utils/imageProxy';
import { writeEmbedToClipboard } from '../../../message_parsing/serializers';
import type { EmbedNodeAttributes } from '../../../message_parsing/types';
import { generateImageFilename, embedPngMetadata } from './imageDownloadUtils';
import { imageGenerationFilename } from './imageGenerationMetadata';

interface ImageFile {
  blob: Blob;
  filename: string;
}

/** Resolve original bytes rather than downloading the resized preview. */
export async function resolveImageEmbedFile(embedId: string): Promise<ImageFile> {
  const epoch = getWorkspaceCacheEpoch();
  const embed = await resolveEmbed(embedId);
  const content = embed?.content;
  const data = typeof content === 'string'
    ? await decodeToonContent(content)
    : content as Record<string, unknown> | undefined;
  if (!data) throw new Error('Image embed is unavailable');

  const files = data.files as Record<string, {
    s3_key?: string; format?: string; aes_nonce?: string; encryption?: string;
  }> | undefined;
  const original = files?.original;
  let blob: Blob;
  if (original?.s3_key) {
    const aesKey = data.aes_key as string | undefined;
    const aesNonce = data.aes_nonce as string | undefined;
    if (!aesKey || !hasMediaEncryptionMetadata(original, aesNonce)) {
      throw new Error('Original image encryption metadata is unavailable');
    }
    const { fetchAndDecryptImage } = await import('./imageEmbedCrypto');
    blob = await fetchAndDecryptImage(
      (data.s3_base_url as string) || '', original.s3_key, aesKey, aesNonce ?? '', original,
    );
    // Variant metadata is authoritative; the crypto cache historically guessed
    // WebP for non-PNG keys, including uploaded JPEGs.
    if (original.format) {
      const format = original.format.toLowerCase().replace(/^image\//, '');
      blob = new Blob([blob], { type: `image/${format === 'jpg' ? 'jpeg' : format === 'svg' ? 'svg+xml' : format}` });
    }
  } else {
    const source = (data.image_url || data.previewImageUrl || data.preview_image_url || data.thumbnail_url) as string | undefined;
    if (!source) throw new Error('Original image is unavailable');
    const response = await fetch(proxyImage(source));
    if (!response.ok) throw new Error(`Image download failed (${response.status})`);
    blob = await response.blob();
    if (!blob.type.startsWith('image/')) throw new Error('Image response is not an image');
  }

  const extension = blob.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png';
  const prompt = data.prompt as string | undefined;
  if (prompt && blob.type === 'image/png') {
    const bytes = embedPngMetadata(await blob.arrayBuffer(), {
      prompt, model: data.model as string | undefined,
      software: 'OpenMates', generatedAt: data.generated_at as string | undefined,
    });
    blob = new Blob([new Uint8Array(bytes)], { type: 'image/png' });
  }
  if (getWorkspaceCacheEpoch() !== epoch) throw new DOMException('Image context changed', 'AbortError');
  const generatedFilename = original?.s3_key && data.app_id === 'images'
    && ['generate', 'generate_draft'].includes(String(data.skill_id))
    ? imageGenerationFilename(data, embedId) : undefined;
  const filename = typeof data.filename === 'string' && data.filename.trim()
    ? data.filename.split(/[\\/]/).pop()!
    : generatedFilename || generateImageFilename(prompt || data.title as string | undefined, extension);
  return { blob, filename };
}

/** Browsers accept PNG image clipboard data; convert other source formats. */
async function clipboardPng(blob: Blob): Promise<Blob> {
  if (blob.type === 'image/png') return blob;
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image clipboard conversion is unavailable');
    context.drawImage(image, 0, 0);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(result => result ? resolve(result) : reject(new Error('Image clipboard conversion failed')), 'image/png');
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function copyImageEmbed(embedId: string, attrs: EmbedNodeAttributes): Promise<void> {
  if (typeof ClipboardItem === 'undefined' || !navigator.clipboard?.write) {
    return Promise.reject(new Error('Image clipboard is unavailable'));
  }
  const epoch = getWorkspaceCacheEpoch();
  const png = resolveImageEmbedFile(embedId).then(async file => {
    const blob = await clipboardPng(file.blob);
    if (getWorkspaceCacheEpoch() !== epoch) throw new DOMException('Image context changed', 'AbortError');
    return blob;
  });
  // Call the clipboard before any await; the PNG promise preserves Safari's
  // gesture while the original file is fetched/decrypted.
  return writeEmbedToClipboard(attrs, '', png);
}

export async function downloadImageEmbed(embedId: string): Promise<void> {
  const { blob, filename } = await resolveImageEmbedFile(embedId);
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Let the browser consume the file before releasing its URL.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
