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
 * Flow:
 * 1. Construct full S3 URL from s3_base_url + s3_key
 * 2. Fetch the encrypted blob
 * 3. Import the AES key via Web Crypto API
 * 4. Decrypt using AES-256-GCM with the provided nonce
 * 5. Return as a Blob for rendering via createObjectURL
 */

/**
 * Fetch an encrypted image from S3 and decrypt it client-side.
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

  return new Blob([decryptedData], { type: mimeType });
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
