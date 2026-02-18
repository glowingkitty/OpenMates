/**
 * uploadService.ts
 *
 * Client-side service for uploading files to the app-uploads microservice.
 *
 * Architecture:
 *   The upload service is a separate microservice (app-uploads) that handles:
 *   - Malware scanning (ClamAV)
 *   - AI-generated image detection (SightEngine)
 *   - Preview generation (Pillow WEBP)
 *   - AES-256-GCM encryption + Vault Transit key wrapping
 *   - S3 upload (chatfiles bucket)
 *
 *   This service sends the file as multipart form data to the upload server,
 *   which is proxied through the main API gateway at /api/uploads/v1/upload/file.
 *
 * Security:
 *   - The auth_refresh_token cookie is sent automatically (same-site, httponly).
 *   - The response includes the plaintext aes_key for client-side rendering
 *     (stored encrypted inside the embed TOON content, never in plaintext at rest).
 *   - The vault_wrapped_aes_key enables server-side skills (images.view) to
 *     decrypt the file on demand via Vault Transit.
 */

// ---------------------------------------------------------------------------
// Response types (mirror UploadFileResponse Pydantic model in upload_route.py)
// ---------------------------------------------------------------------------

export interface FileVariantMetadata {
  /** S3 object key for this variant */
  s3_key: string;
  /** Image width in pixels */
  width: number;
  /** Image height in pixels */
  height: number;
  /** Encrypted file size in bytes */
  size_bytes: number;
  /** Image format (always 'webp' for Phase 1) */
  format: string;
}

export interface AIDetectionMetadata {
  /** Probability (0.0–1.0) that the image is AI-generated */
  ai_generated: number;
  /** Detection provider name (e.g. 'sightengine') */
  provider: string;
}

export interface UploadFileResponse {
  /** UUID used as embed_id in the embed system */
  embed_id: string;
  /** Original uploaded filename */
  filename: string;
  /** Detected MIME type */
  content_type: string;
  /** SHA-256 hash of the original file content */
  content_hash: string;
  /** Stored file variants (original, preview) */
  files: Record<string, FileVariantMetadata>;
  /** S3 base URL for constructing full file URLs */
  s3_base_url: string;
  /** Base64 AES-256 key for client-side decryption — stored encrypted in embed TOON */
  aes_key: string;
  /** Base64 AES-GCM nonce shared across all encrypted variants */
  aes_nonce: string;
  /** Vault-wrapped AES key for server-side skill access — stored encrypted in embed TOON */
  vault_wrapped_aes_key: string;
  /** ClamAV result: always 'clean' */
  malware_scan: string;
  /** AI-generated detection result (images only, may be null) */
  ai_detection: AIDetectionMetadata | null;
  /** True if this file was already uploaded by this user (deduplication hit) */
  deduplicated: boolean;
}

// ---------------------------------------------------------------------------
// Upload function
// ---------------------------------------------------------------------------

/**
 * Upload a file to the uploads microservice.
 *
 * The endpoint is proxied through the API gateway — the browser sends the
 * auth_refresh_token cookie automatically because it's same-site/httponly.
 *
 * @param file - The File object to upload.
 * @returns The upload response with S3 keys, AES key, and embed metadata.
 * @throws Error if the upload fails (network error, server error, or malware detection).
 */
export async function uploadFileToServer(
  file: File,
): Promise<UploadFileResponse> {
  const formData = new FormData();
  formData.append("file", file);

  // The uploads service is proxied at /api/uploads/ by Caddy/Nginx.
  // Cookies (auth_refresh_token) are forwarded automatically.
  const uploadUrl = "/api/uploads/v1/upload/file";

  let response: Response;
  try {
    response = await fetch(uploadUrl, {
      method: "POST",
      body: formData,
      // Credentials: 'include' ensures cookies are sent cross-origin if needed.
      // For same-origin requests this is the default, but we set it explicitly.
      credentials: "include",
    });
  } catch (networkError) {
    console.error(
      "[UploadService] Network error uploading file:",
      networkError,
    );
    throw new Error(
      "Upload failed: network error. Please check your connection.",
    );
  }

  if (!response.ok) {
    let errorDetail = `Upload failed with status ${response.status}`;
    try {
      const errorBody = await response.json();
      errorDetail = errorBody.detail || errorDetail;
    } catch {
      // Response body is not JSON — use the status text
      errorDetail = `Upload failed: ${response.statusText || response.status}`;
    }

    // Map specific HTTP codes to user-friendly messages
    if (response.status === 401) {
      throw new Error(
        "Upload failed: not authenticated. Please reload the page.",
      );
    } else if (response.status === 413) {
      throw new Error("Upload failed: file too large (maximum 100 MB).");
    } else if (response.status === 415) {
      throw new Error(`Upload failed: unsupported file type. ${errorDetail}`);
    } else if (response.status === 422) {
      // Malware detected
      throw new Error(`Upload rejected: ${errorDetail}`);
    } else if (response.status === 429) {
      throw new Error("Upload failed: too many uploads. Please wait a moment.");
    } else if (response.status >= 500) {
      console.error(
        "[UploadService] Server error:",
        response.status,
        errorDetail,
      );
      throw new Error("Upload failed: server error. Please try again.");
    }

    throw new Error(errorDetail);
  }

  try {
    const data: UploadFileResponse = await response.json();
    return data;
  } catch (parseError) {
    console.error(
      "[UploadService] Failed to parse upload response:",
      parseError,
    );
    throw new Error("Upload failed: unexpected server response format.");
  }
}
