/**
 * frontend/packages/ui/src/components/embeds/images/imageEmbedCrypto.ts
 *
 * Utility for fetching AES-256-GCM encrypted image blobs from Hetzner S3
 * and decrypting them client-side using the Web Crypto API.
 *
 * The chatfiles S3 bucket is public-read, so blobs can be fetched directly
 * via HTTP GET. However, the content is AES-256-GCM encrypted before upload.
 * The plaintext AES key and nonce are included in the embed content (which
 * itself is client-encrypted with the chat's master key).
 *
 * Includes an in-memory cache of decrypted blob URLs keyed by S3 key,
 * so that re-mounting a component (e.g. scrolling away and back) does not
 * trigger a redundant fetch + decrypt cycle.
 *
 * Flow:
 * 1. Check in-memory cache for existing blob URL
 * 2. If miss: construct full S3 URL from s3_base_url + s3_key
 * 3. Fetch the encrypted blob
 * 4. Import the AES key via Web Crypto API
 * 5. Decrypt using AES-256-GCM with the provided nonce
 * 6. Create blob URL, store in cache, return
 */

/**
 * In-memory cache: maps S3 key -> blob URL.
 *
 * This survives component unmounts so images don't need to be re-fetched
 * and re-decrypted when a preview or fullscreen component remounts.
 * Blob URLs are reference-counted: each component that uses a cached URL
 * calls `retainCachedImage` on mount and `releaseCachedImage` on unmount.
 * When the ref count drops to zero the blob URL is revoked after a grace
 * period to free memory.
 */
const imageCache = new Map<
  string,
  {
    blobUrl: string;
    refCount: number;
    revokeTimer: ReturnType<typeof setTimeout> | null;
  }
>();

/** Grace period before revoking an unreferenced blob URL (ms). */
const REVOKE_GRACE_MS = 30_000;

/**
 * Increment the reference count for a cached blob URL.
 * Call this when a component mounts and starts using the URL.
 */
export function retainCachedImage(s3Key: string): void {
  const entry = imageCache.get(s3Key);
  if (!entry) return;
  entry.refCount++;
  // Cancel any pending revocation since someone is using it again
  if (entry.revokeTimer) {
    clearTimeout(entry.revokeTimer);
    entry.revokeTimer = null;
  }
}

/**
 * Decrement the reference count for a cached blob URL.
 * When it reaches zero, schedule revocation after a grace period.
 * Call this when a component unmounts.
 */
export function releaseCachedImage(s3Key: string): void {
  const entry = imageCache.get(s3Key);
  if (!entry) return;
  entry.refCount = Math.max(0, entry.refCount - 1);
  if (entry.refCount === 0 && !entry.revokeTimer) {
    entry.revokeTimer = setTimeout(() => {
      // Double-check ref count hasn't increased since timer was set
      const current = imageCache.get(s3Key);
      if (current && current.refCount === 0) {
        URL.revokeObjectURL(current.blobUrl);
        imageCache.delete(s3Key);
      }
    }, REVOKE_GRACE_MS);
  }
}

/**
 * Get a cached blob URL if available, without fetching.
 */
export function getCachedImageUrl(s3Key: string): string | undefined {
  return imageCache.get(s3Key)?.blobUrl;
}

/**
 * Fetch an encrypted image from S3 and decrypt it client-side.
 * Results are cached in memory keyed by s3Key so that subsequent calls
 * for the same image return instantly.
 *
 * @param s3BaseUrl - Base URL of the S3 bucket (e.g. "https://openmates-chatfiles.nbg1.your-objectstorage.com")
 * @param s3Key - Relative file key in the bucket (e.g. "user_id/timestamp_id_preview.webp")
 * @param aesKeyBase64 - Base64-encoded plaintext AES-256 key (32 bytes)
 * @param nonceBase64 - Base64-encoded GCM nonce (12 bytes)
 * @returns Decrypted image as a Blob
 */
export async function fetchAndDecryptImage(
  s3BaseUrl: string,
  s3Key: string,
  aesKeyBase64: string,
  nonceBase64: string,
): Promise<Blob> {
  // 0. Check cache first — return existing blob if we already decrypted this image
  const cached = imageCache.get(s3Key);
  if (cached) {
    // Return a fresh Blob reference from the cached blob URL.
    // The caller will create its own objectURL, but we also keep our canonical one.
    // Actually, callers use URL.createObjectURL on the returned Blob, so just
    // fetch the blob from the cached URL to avoid re-decrypting.
    // Simpler: re-fetch from blob URL (instant, no network)
    const resp = await fetch(cached.blobUrl);
    return resp.blob();
  }

  // 1. Construct the full S3 URL
  const url = `${s3BaseUrl}/${s3Key}`;

  // 2. Fetch the encrypted blob from S3 (public-read, CORS enabled)
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Failed to fetch encrypted image from S3: ${response.status} ${response.statusText} (${url})`,
    );
  }
  const encryptedData = await response.arrayBuffer();

  // 3. Decode the base64 AES key and nonce
  const aesKeyBytes = base64ToArrayBuffer(aesKeyBase64);
  const nonceBytes = base64ToArrayBuffer(nonceBase64);

  // 4. Import the AES key for Web Crypto API
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    aesKeyBytes,
    { name: "AES-GCM" },
    false, // not extractable
    ["decrypt"],
  );

  // 5. Decrypt using AES-256-GCM
  // Note: AES-GCM ciphertext includes the 16-byte auth tag at the end
  const decryptedData = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: nonceBytes,
      // No additional data (AAD) — matches server-side encrypt(nonce, content, None)
    },
    cryptoKey,
    encryptedData,
  );

  // 6. Determine MIME type from the s3_key extension
  const mimeType = s3Key.endsWith(".png") ? "image/png" : "image/webp";

  const blob = new Blob([decryptedData], { type: mimeType });

  // 7. Cache the decrypted blob URL for future use
  const blobUrl = URL.createObjectURL(blob);
  imageCache.set(s3Key, { blobUrl, refCount: 0, revokeTimer: null });

  return blob;
}

/**
 * Convert a base64 string to an ArrayBuffer.
 * Handles both standard and URL-safe base64.
 */
function base64ToArrayBuffer(base64: string): ArrayBuffer {
  // Normalize URL-safe base64 to standard base64
  const normalized = base64.replace(/-/g, "+").replace(/_/g, "/");
  const binaryString = atob(normalized);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}
