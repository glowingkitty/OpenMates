/**
 * frontend/packages/ui/src/components/embeds/images/imageEmbedCrypto.ts
 *
 * Utility for fetching AES-256-GCM encrypted image blobs from Hetzner S3
 * and decrypting them client-side using the Web Crypto API.
 *
 * The chatfiles S3 bucket is private — blobs require a presigned URL from
 * the backend API. The content is AES-256-GCM encrypted before upload.
 * The plaintext AES key and nonce are included in the embed content (which
 * itself is client-encrypted with the chat's master key in IndexedDB).
 *
 * Includes an in-memory cache of decrypted blob URLs keyed by S3 key,
 * so that re-mounting a component (e.g. scrolling away and back) does not
 * trigger a redundant fetch + decrypt cycle.
 *
 * Flow:
 * 1. Check in-memory cache for existing blob URL
 * 2. If miss: request a presigned URL from GET /v1/embeds/presigned-url
 * 3. Fetch the encrypted blob from S3 using the presigned URL
 * 4. Import the AES key via Web Crypto API
 * 5. Decrypt using AES-256-GCM with the provided nonce
 * 6. Create blob URL, store in cache, return
 */

import { fetchWithPresignedUrl } from "../../../services/presignedUrlService";
import {
  decryptMediaPayload,
} from "../../../services/encryption/mediaEncryption";

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
type CachedImage = {
  blob: Blob;
  blobUrl: string;
  refCount: number;
  revokeTimer: ReturnType<typeof setTimeout> | null;
};
const imageCache = new Map<string, CachedImage>();
const pendingImages = new Map<string, Promise<Blob>>();
const REVOKE_GRACE_MS = 30_000;
const MAX_CACHED_IMAGE_BYTES = 64 * 1024 * 1024;
let cachedBytes = 0;
let trimTimer: ReturnType<typeof setTimeout> | null = null;

function evictImage(s3Key: string, entry: CachedImage): void {
  if (imageCache.get(s3Key) !== entry || entry.refCount > 0) return;
  if (entry.revokeTimer) clearTimeout(entry.revokeTimer);
  URL.revokeObjectURL(entry.blobUrl);
  imageCache.delete(s3Key);
  cachedBytes -= entry.blob.size;
}

function trimUnusedImages(): void {
  trimTimer = null;
  for (const [key, entry] of Array.from(imageCache)) {
    if (cachedBytes <= MAX_CACHED_IMAGE_BYTES) break;
    evictImage(key, entry);
  }
}

function scheduleImageRelease(s3Key: string, entry: CachedImage): void {
  if (entry.refCount !== 0 || entry.revokeTimer) return;
  entry.revokeTimer = setTimeout(() => evictImage(s3Key, entry), REVOKE_GRACE_MS);
  // Let awaiting consumers acquire their references before enforcing the budget.
  if (cachedBytes > MAX_CACHED_IMAGE_BYTES && trimTimer === null) {
    trimTimer = setTimeout(trimUnusedImages, 0);
  }
}

export function retainCachedImage(s3Key: string): void {
  const entry = imageCache.get(s3Key);
  if (!entry) return;
  entry.refCount++;
  if (entry.revokeTimer) clearTimeout(entry.revokeTimer);
  entry.revokeTimer = null;
}

export function releaseCachedImage(s3Key: string): void {
  const entry = imageCache.get(s3Key);
  if (!entry) return;
  entry.refCount = Math.max(0, entry.refCount - 1);
  scheduleImageRelease(s3Key, entry);
}

export function getCachedImageUrl(s3Key: string): string | undefined {
  const entry = imageCache.get(s3Key);
  if (!entry) return undefined;
  imageCache.delete(s3Key);
  imageCache.set(s3Key, entry);
  return entry.blobUrl;
}

/** One reference per component/key, including repeated effects and late loads. */
export function createImageUrlOwner() {
  const keys = new Set<string>();
  let disposed = false;
  return {
    retain(key: string): void {
      if (disposed || keys.has(key) || !imageCache.has(key)) return;
      retainCachedImage(key);
      keys.add(key);
    },
    release(key: string): void {
      if (keys.delete(key)) releaseCachedImage(key);
    },
    destroy(): void {
      disposed = true;
      for (const key of Array.from(keys)) releaseCachedImage(key);
      keys.clear();
    },
  };
}

/**
 * Fetch an encrypted image from S3 and decrypt it client-side.
 * Results are cached in memory keyed by s3Key so that subsequent calls
 * for the same image return instantly.
 *
 * The chatfiles S3 bucket is private — a presigned URL is obtained from the
 * backend API (GET /v1/embeds/presigned-url) before fetching. If the URL
 * expires (HTTP 403), a fresh one is requested and the fetch is retried once.
 *
 * @param s3BaseUrl - Base URL of the S3 bucket (unused, kept for interface compat — presigned URL is used instead)
 * @param s3Key - Relative file key in the bucket (e.g. "user_id/timestamp_id_preview.webp")
 * @param aesKeyBase64 - Base64-encoded plaintext AES-256 key (32 bytes)
 * @param nonceBase64 - Base64-encoded GCM nonce (12 bytes), OR empty string "" if the
 *   nonce is prepended as the first 12 bytes of the ciphertext (PDF screenshot artefacts
 *   use this format to ensure each S3 object has a unique nonce).
 * @returns Decrypted image as a Blob
 */
export async function fetchAndDecryptImage(
  s3BaseUrl: string,
  s3Key: string,
  aesKeyBase64: string,
  nonceBase64: string,
  variant: unknown = {},
): Promise<Blob> {
  const cached = imageCache.get(s3Key);
  if (cached) {
    getCachedImageUrl(s3Key); // Touch LRU without fetching our own blob URL.
    return cached.blob;
  }
  const pending = pendingImages.get(s3Key);
  if (pending) return pending;

  const request = (async () => {
    const encryptedData = await fetchWithPresignedUrl(s3Key);
    const decryptedData = await decryptMediaPayload({
      encryptedData,
      aesKeyBase64,
      variant,
      legacyNonceBase64: nonceBase64,
    });
    const mimeType = s3Key.endsWith(".png") ? "image/png" : "image/webp";
    const blob = new Blob([decryptedData], { type: mimeType });
    const entry: CachedImage = {
      blob,
      blobUrl: URL.createObjectURL(blob),
      refCount: 0,
      revokeTimer: null,
    };
    imageCache.set(s3Key, entry);
    cachedBytes += blob.size;
    // Also expires download-only and abandoned requests with no component owner.
    scheduleImageRelease(s3Key, entry);
    return blob;
  })();
  pendingImages.set(s3Key, request);
  try {
    return await request;
  } finally {
    pendingImages.delete(s3Key);
  }
}
