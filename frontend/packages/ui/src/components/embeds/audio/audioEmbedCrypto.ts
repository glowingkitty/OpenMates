/**
 * frontend/packages/ui/src/components/embeds/audio/audioEmbedCrypto.ts
 *
 * Utility for fetching AES-256-GCM encrypted audio blobs from Hetzner S3
 * and decrypting them client-side using the Web Crypto API.
 *
 * Architecture mirrors imageEmbedCrypto.ts:
 * - The chatfiles S3 bucket is public-read, so blobs are fetched directly.
 * - Audio content is AES-256-GCM encrypted before upload.
 * - The plaintext AES key and nonce are included in the embed node attrs.
 * - An in-memory cache prevents re-fetching on component re-mounts.
 *
 * Usage:
 *   const blobUrl = await fetchAndDecryptAudio(s3BaseUrl, s3Key, aesKey, aesNonce, mimeType);
 *   // pass blobUrl to <audio src={blobUrl}>
 *   // call releaseAudio(s3Key) on component unmount to free memory
 */

/** In-memory cache: maps S3 key → { blobUrl, refCount, revokeTimer } */
const audioCache = new Map<
  string,
  {
    blobUrl: string;
    refCount: number;
    revokeTimer: ReturnType<typeof setTimeout> | null;
  }
>();

/** Grace period before revoking an unreferenced blob URL (ms). */
const REVOKE_GRACE_MS = 60_000;

/**
 * Increment reference count for a cached audio blob URL.
 * Call on component mount to prevent premature revocation.
 */
export function retainCachedAudio(s3Key: string): void {
  const entry = audioCache.get(s3Key);
  if (!entry) return;
  entry.refCount++;
  if (entry.revokeTimer) {
    clearTimeout(entry.revokeTimer);
    entry.revokeTimer = null;
  }
}

/**
 * Decrement reference count for a cached audio blob URL.
 * Schedules revocation after a grace period when count reaches zero.
 * Call on component unmount.
 */
export function releaseCachedAudio(s3Key: string): void {
  const entry = audioCache.get(s3Key);
  if (!entry) return;
  entry.refCount = Math.max(0, entry.refCount - 1);
  if (entry.refCount === 0 && !entry.revokeTimer) {
    entry.revokeTimer = setTimeout(() => {
      const current = audioCache.get(s3Key);
      if (current && current.refCount === 0) {
        URL.revokeObjectURL(current.blobUrl);
        audioCache.delete(s3Key);
      }
    }, REVOKE_GRACE_MS);
  }
}

/**
 * Get a cached blob URL without fetching.
 */
export function getCachedAudioUrl(s3Key: string): string | undefined {
  return audioCache.get(s3Key)?.blobUrl;
}

/**
 * Fetch an AES-256-GCM encrypted audio file from S3 and decrypt it.
 * Results are cached in memory keyed by s3Key.
 *
 * @param s3BaseUrl  - S3 bucket base URL (e.g. "https://openmates-chatfiles.nbg1.your-objectstorage.com")
 * @param s3Key      - File key in the bucket (e.g. "user_id/timestamp_recording.webm")
 * @param aesKeyBase64 - Base64-encoded plaintext AES-256 key (32 bytes)
 * @param nonceBase64  - Base64-encoded AES-GCM nonce (12 bytes)
 * @param mimeType   - MIME type of the audio (e.g. "audio/webm", "audio/mp4")
 * @returns Decrypted audio blob URL (object URL — caller should not revoke directly)
 */
export async function fetchAndDecryptAudio(
  s3BaseUrl: string,
  s3Key: string,
  aesKeyBase64: string,
  nonceBase64: string,
  mimeType: string = "audio/webm",
): Promise<string> {
  // Return cached blob URL if available
  const cached = audioCache.get(s3Key);
  if (cached) {
    cached.refCount++;
    // Cancel pending revocation
    if (cached.revokeTimer) {
      clearTimeout(cached.revokeTimer);
      cached.revokeTimer = null;
    }
    return cached.blobUrl;
  }

  // Construct full S3 URL
  const url = `${s3BaseUrl}/${s3Key}`;

  // Fetch the encrypted blob
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Failed to fetch encrypted audio from S3: ${response.status} ${response.statusText} (${url})`,
    );
  }
  const encryptedData = await response.arrayBuffer();

  // Decode base64 key and nonce
  const aesKeyBytes = base64ToArrayBuffer(aesKeyBase64);
  const nonceBytes = base64ToArrayBuffer(nonceBase64);

  // Import AES key
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    aesKeyBytes,
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );

  // Decrypt using AES-256-GCM
  const decryptedData = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: nonceBytes },
    cryptoKey,
    encryptedData,
  );

  // Create blob URL and cache it
  const blob = new Blob([decryptedData], { type: mimeType });
  const blobUrl = URL.createObjectURL(blob);
  audioCache.set(s3Key, { blobUrl, refCount: 1, revokeTimer: null });

  return blobUrl;
}

/**
 * Convert a base64 string to an ArrayBuffer.
 * Handles both standard and URL-safe base64.
 */
function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const normalized = base64.replace(/-/g, "+").replace(/_/g, "/");
  const binaryString = atob(normalized);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}
