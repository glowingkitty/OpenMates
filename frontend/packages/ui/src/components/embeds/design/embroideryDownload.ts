/**
 * frontend/packages/ui/src/components/embeds/design/embroideryDownload.ts
 *
 * Reads the machine files of an embroidery result for download. Each file is
 * fetched encrypted from storage and decrypted in the browser with the embed's
 * own key material, then saved from a same-origin object URL so the browser
 * honours the suggested file name. Component previews carry inline text
 * (`previewDownloadText`) and need no network.
 */
import JSZip from 'jszip';
import { fetchAndDecryptImage } from '../images/imageEmbedCrypto';
import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
import { EMBROIDERY_FORMATS, type EmbroideryDesign, type EmbroideryFormat } from './embroideryDesign';

export type EmbroideryDownloadSource = Pick<
  EmbroideryDesign, 'files' | 's3BaseUrl' | 'aesKey' | 'aesNonce' | 'previewDownloadText'
>;

/** Decrypted bytes of one machine file. Throws when the file cannot be read. */
export async function readEmbroideryFile(design: EmbroideryDownloadSource, format: EmbroideryFormat): Promise<Blob> {
  if (design.previewDownloadText) return new Blob([design.previewDownloadText]);
  const file = design.files[format];
  const nonce = file?.aes_nonce ?? design.aesNonce;
  if (!file || !design.aesKey || !hasMediaEncryptionMetadata(file, nonce)) {
    throw new Error(`Embroidery file ${format} is not available`);
  }
  // The helper labels the bytes as an image; only the bytes are used here.
  const decrypted = await fetchAndDecryptImage(design.s3BaseUrl, file.s3_key, design.aesKey, nonce, file);
  return new Blob([await decrypted.arrayBuffer()], { type: 'application/octet-stream' });
}

/** Hand a blob to the browser as a download with the given file name. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Save one machine file as "<baseName>.<format>". */
export async function downloadEmbroideryFile(
  design: EmbroideryDownloadSource, format: EmbroideryFormat, baseName: string,
): Promise<void> {
  saveBlob(await readEmbroideryFile(design, format), `${baseName || 'embroidery'}.${format}`);
}

/** Save all machine formats in one "<baseName>.zip". Fails as a whole when any file is missing. */
export async function downloadAllEmbroideryFiles(design: EmbroideryDownloadSource, baseName: string): Promise<void> {
  const name = baseName || 'embroidery';
  const zip = new JSZip();
  const files = await Promise.all(EMBROIDERY_FORMATS.map((format) => readEmbroideryFile(design, format)));
  EMBROIDERY_FORMATS.forEach((format, index) => zip.file(`${name}.${format}`, files[index]));
  saveBlob(await zip.generateAsync({ type: 'blob' }), `${name}.zip`);
}
