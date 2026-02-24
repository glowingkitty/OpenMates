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
 *   The upload server is a SEPARATE VM (not proxied through the web app server).
 *   The web app is a static site — it has no server-side proxy.
 *   The upload URL is configured via VITE_UPLOAD_URL* build-time env vars (see config/api.ts).
 *   Both dev and prod use the same upload server: https://upload.openmates.org
 *   There is only one upload server — the X-Target-Env header (set by Caddy based on the Origin)
 *   tells the upload server whether the request is from the dev or prod web app.
 *
 * Security:
 *   - The auth_refresh_token cookie is sent automatically (same-site, httponly).
 *   - The response includes the plaintext aes_key for client-side rendering
 *     (stored encrypted inside the embed TOON content, never in plaintext at rest).
 *   - The vault_wrapped_aes_key enables server-side skills (images.view) to
 *     decrypt the file on demand via Vault Transit.
 */

import { getUploadUrl } from "../../../config/api.js";

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
  /**
   * Number of pages in the PDF (only present for application/pdf uploads).
   * Returned by the upload server after pymupdf page-count extraction.
   */
  page_count?: number;
}

// ---------------------------------------------------------------------------
// Upload function
// ---------------------------------------------------------------------------

/**
 * Upload a file to the uploads microservice.
 *
 * The upload server is a separate VM reachable at its own domain.
 * Cookies (auth_refresh_token) are sent cross-origin via credentials: 'include'.
 *
 * Uses XMLHttpRequest (instead of fetch) so we can fire onprogress callbacks
 * that report upload percentage to the pending-send progress UI.
 *
 * @param file - The File object to upload.
 * @param signal - Optional AbortSignal to cancel the upload mid-flight.
 * @param onProgress - Optional callback receiving upload progress 0–100.
 * @returns The upload response with S3 keys, AES key, and embed metadata.
 * @throws Error if the upload fails (network error, server error, or malware detection).
 *         Throws an AbortError (name === 'AbortError') if the upload is cancelled.
 */
export async function uploadFileToServer(
  file: File,
  signal?: AbortSignal,
  onProgress?: (percent: number) => void,
): Promise<UploadFileResponse> {
  const formData = new FormData();
  formData.append("file", file);

  // Build the full absolute URL to the upload server.
  // The upload server is a separate VM — NOT a relative path on the web app.
  // getUploadUrl() reads VITE_UPLOAD_URL* build-time env vars (see config/api.ts).
  const uploadUrl = `${getUploadUrl()}/v1/upload/file`;

  return new Promise<UploadFileResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    // --- AbortSignal integration ---
    // When the caller aborts (e.g. user removes the embed, upload is cancelled),
    // abort the XHR and reject with an AbortError so the caller can distinguish
    // cancellation from a genuine upload failure.
    const onAbort = () => {
      xhr.abort();
    };
    if (signal) {
      if (signal.aborted) {
        // Already aborted before we even started
        const abortErr = new DOMException("Upload aborted", "AbortError");
        reject(abortErr);
        return;
      }
      signal.addEventListener("abort", onAbort, { once: true });
    }

    // --- Upload progress ---
    if (onProgress) {
      xhr.upload.addEventListener("progress", (evt) => {
        if (evt.lengthComputable && evt.total > 0) {
          const percent = Math.round((evt.loaded / evt.total) * 100);
          onProgress(percent);
        }
      });
    }

    // --- Completion ---
    xhr.addEventListener("load", () => {
      // Clean up the abort listener (no-op if signal already fired)
      signal?.removeEventListener("abort", onAbort);

      if (xhr.status >= 200 && xhr.status < 300) {
        // Success — parse JSON response
        try {
          const data: UploadFileResponse = JSON.parse(xhr.responseText);
          onProgress?.(100); // Ensure we report 100% on success
          resolve(data);
        } catch (parseError) {
          console.error(
            "[UploadService] Failed to parse upload response:",
            parseError,
          );
          reject(
            new Error("Upload failed: unexpected server response format."),
          );
        }
        return;
      }

      // HTTP error — map to user-friendly messages
      let errorDetail = `Upload failed with status ${xhr.status}`;
      try {
        const errorBody = JSON.parse(xhr.responseText);
        errorDetail = errorBody.detail || errorDetail;
      } catch {
        // Response body is not JSON — use status text
        errorDetail = `Upload failed: ${xhr.statusText || xhr.status}`;
      }

      if (xhr.status === 401) {
        reject(
          new Error(
            "Upload failed: not authenticated. Please reload the page.",
          ),
        );
      } else if (xhr.status === 413) {
        reject(new Error("Upload failed: file too large (maximum 100 MB)."));
      } else if (xhr.status === 415) {
        reject(
          new Error(`Upload failed: unsupported file type. ${errorDetail}`),
        );
      } else if (xhr.status === 422) {
        // Malware detected
        reject(new Error(`Upload rejected: ${errorDetail}`));
      } else if (xhr.status === 429) {
        reject(
          new Error("Upload failed: too many uploads. Please wait a moment."),
        );
      } else if (xhr.status >= 500) {
        console.error("[UploadService] Server error:", xhr.status, errorDetail);
        reject(new Error("Upload failed: server error. Please try again."));
      } else {
        reject(new Error(errorDetail));
      }
    });

    // --- Network error ---
    xhr.addEventListener("error", () => {
      signal?.removeEventListener("abort", onAbort);
      console.error("[UploadService] Network error uploading file");
      reject(
        new Error(
          "Upload failed: network error. Please check your connection.",
        ),
      );
    });

    // --- XHR abort (triggered by our onAbort listener above) ---
    xhr.addEventListener("abort", () => {
      signal?.removeEventListener("abort", onAbort);
      reject(new DOMException("Upload aborted", "AbortError"));
    });

    // --- Timeout ---
    xhr.addEventListener("timeout", () => {
      signal?.removeEventListener("abort", onAbort);
      reject(new Error("Upload failed: request timed out."));
    });

    // 10-minute timeout for large files (same limit the server enforces)
    xhr.timeout = 10 * 60 * 1000;

    xhr.withCredentials = true; // send auth cookies cross-origin
    xhr.open("POST", uploadUrl);
    xhr.send(formData);
  });
}
