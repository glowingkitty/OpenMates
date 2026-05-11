/**
 * frontend/packages/ui/src/components/embeds/docs/docsArtifactCrypto.ts
 *
 * Fetches AES-256-GCM encrypted Docs app artifacts from the private chatfiles
 * bucket through the shared presigned URL service. DOCX artifacts and preview
 * page PNGs use the nonce-prefixed ciphertext format already used by PDF
 * screenshots: first 12 bytes are the nonce, remainder is ciphertext+tag.
 */

import { fetchWithPresignedUrl } from '../../../services/presignedUrlService';

const NONCE_BYTES = 12;

export async function fetchAndDecryptDocArtifact(
  s3Key: string,
  aesKeyBase64: string,
  mimeType: string,
): Promise<Blob> {
  const encryptedData = await fetchWithPresignedUrl(s3Key);
  const nonceBuffer = encryptedData.slice(0, NONCE_BYTES);
  const ciphertext = encryptedData.slice(NONCE_BYTES);
  const aesKeyBytes = base64ToArrayBuffer(aesKeyBase64);
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    aesKeyBytes,
    { name: 'AES-GCM' },
    false,
    ['decrypt'],
  );
  const decryptedData = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: nonceBuffer },
    cryptoKey,
    ciphertext,
  );
  return new Blob([decryptedData], { type: mimeType });
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}
