/**
 * frontend/packages/ui/src/services/presignedUrlService.ts
 *
 * Shared service for fetching presigned S3 URLs from the backend API.
 *
 * Architecture:
 *   The chatfiles S3 bucket is private — encrypted blobs cannot be fetched
 *   directly via HTTP GET. Instead, the client requests a short-lived (15-min)
 *   presigned URL from the backend, which grants anonymous GET access to one
 *   S3 object. Even with the URL, the content is useless without the AES key
 *   (which lives only in the client-encrypted embed content in IndexedDB).
 *
 *   This service provides:
 *   - getPresignedUrl(): fetches a presigned URL from GET /v1/embeds/presigned-url
 *   - fetchWithPresignedUrl(): fetches the S3 blob, retrying once with a fresh
 *     presigned URL on 403 (expired URL)
 *
 *   Used by:
 *   - audioEmbedCrypto.ts (encrypted audio playback)
 *   - imageEmbedCrypto.ts (encrypted image rendering)
 */

import { getApiUrl } from "../config/api";

/**
 * Error thrown when presigned URL generation fails on the backend.
 */
export class PresignedUrlError extends Error {
  constructor(
    public readonly s3Key: string,
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "PresignedUrlError";
  }
}

/**
 * Fetch a presigned URL for an S3 object from the backend API.
 *
 * Calls GET /v1/embeds/presigned-url?s3_key=... with session credentials.
 * The returned URL is valid for 15 minutes.
 *
 * @param s3Key - S3 object key (e.g. "user-uuid/hash/timestamp_original.bin")
 * @returns Presigned URL string
 * @throws PresignedUrlError if the backend rejects the request
 */
export async function getPresignedUrl(s3Key: string): Promise<string> {
  const apiUrl = getApiUrl();
  const endpoint = `${apiUrl}/v1/embeds/presigned-url?s3_key=${encodeURIComponent(s3Key)}`;

  const response = await fetch(endpoint, {
    method: "GET",
    credentials: "include", // Send session cookie for authentication
  });

  if (!response.ok) {
    throw new PresignedUrlError(
      s3Key,
      response.status,
      `Presigned URL request failed: ${response.status} ${response.statusText}`,
    );
  }

  const data = await response.json();
  return data.url;
}

/**
 * Fetch an S3 blob using a presigned URL, with automatic retry on 403.
 *
 * If the first fetch returns HTTP 403 (expired or invalid presigned URL),
 * requests a fresh presigned URL from the backend and retries once.
 * This handles the case where a cached presigned URL has expired.
 *
 * @param s3Key - S3 object key (used to request a new presigned URL on retry)
 * @returns ArrayBuffer containing the raw S3 object bytes (encrypted ciphertext)
 * @throws Error if both attempts fail
 */
export async function fetchWithPresignedUrl(
  s3Key: string,
): Promise<ArrayBuffer> {
  // First attempt: get a presigned URL and fetch the blob
  let presignedUrl = await getPresignedUrl(s3Key);
  let response = await fetch(presignedUrl);

  // If 403 (expired URL), retry once with a fresh presigned URL
  if (response.status === 403) {
    presignedUrl = await getPresignedUrl(s3Key);
    response = await fetch(presignedUrl);
  }

  if (!response.ok) {
    throw new Error(
      `S3 fetch failed for ${s3Key}: ${response.status} ${response.statusText}`,
    );
  }

  return response.arrayBuffer();
}
