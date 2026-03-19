// frontend/packages/openmates-cli/src/uploadService.ts
/**
 * @file File upload service for the CLI — uploads images and PDFs to
 * the OpenMates upload server (S3-backed, encrypted, malware-scanned).
 *
 * Uses multipart/form-data POST to upload.openmates.org, authenticated
 * via the auth_refresh_token cookie from pair-auth login.
 *
 * Mirrors: uploadService.ts (web app) — same endpoint, same auth, same response format.
 * Architecture: docs/architecture/embeds.md
 */

import { readFileSync } from "node:fs";
import { basename } from "node:path";
import type { OpenMatesSession } from "./storage.js";

// ── Types (mirrors web app uploadService.ts) ───────────────────────────

export interface FileVariantMetadata {
  s3_key: string;
  width: number;
  height: number;
  size_bytes: number;
  format: string;
}

export interface AIDetectionMetadata {
  ai_generated: number;
  provider: string;
}

export interface UploadFileResponse {
  embed_id: string;
  filename: string;
  content_type: string;
  content_hash: string;
  files: Record<string, FileVariantMetadata>;
  s3_base_url: string;
  aes_key: string;
  aes_nonce: string;
  vault_wrapped_aes_key: string;
  malware_scan: string;
  ai_detection: AIDetectionMetadata | null;
  deduplicated: boolean;
  page_count?: number;
}

// ── Upload URL resolution ──────────────────────────────────────────────

/**
 * Derive the upload server URL from the API URL.
 * api.openmates.org → upload.openmates.org
 * api.dev.openmates.org → upload.dev.openmates.org
 */
function getUploadUrl(apiUrl: string): string {
  try {
    const url = new URL(apiUrl);
    // Replace "api." prefix with "upload."
    url.hostname = url.hostname.replace(/^api\./, "upload.");
    // Upload server uses HTTPS on port 443
    url.port = "";
    return url.origin;
  } catch {
    return "https://upload.openmates.org";
  }
}

// ── Upload function ────────────────────────────────────────────────────

/**
 * Upload a file to the OpenMates upload server.
 *
 * Sends a multipart/form-data POST with the file and auth cookie.
 * The server handles: malware scan, content safety check, encryption,
 * preview generation, and S3 storage.
 *
 * Mirrors: uploadService.ts uploadFileToServer()
 *
 * @param filePath Local file path to upload
 * @param session The user's session (for auth cookie and API URL)
 * @returns Upload response with S3 metadata and encryption keys
 */
export async function uploadFile(
  filePath: string,
  session: OpenMatesSession,
): Promise<UploadFileResponse> {
  const filename = basename(filePath);
  const fileBytes = readFileSync(filePath);

  const uploadUrl = `${getUploadUrl(session.apiUrl)}/v1/upload/file`;

  // Build multipart form data manually for Node.js
  // (native fetch supports FormData with Blob since Node 18)
  const blob = new Blob([fileBytes]);
  const formData = new FormData();
  formData.append("file", blob, filename);

  // Construct cookie header from session
  const cookies: string[] = [];
  if (session.cookies?.auth_refresh_token) {
    cookies.push(`auth_refresh_token=${session.cookies.auth_refresh_token}`);
  }

  const response = await fetch(uploadUrl, {
    method: "POST",
    body: formData,
    headers: {
      ...(cookies.length > 0 ? { Cookie: cookies.join("; ") } : {}),
    },
    signal: AbortSignal.timeout(10 * 60 * 1000), // 10-minute timeout
  });

  if (!response.ok) {
    const status = response.status;
    let errorMessage: string;
    switch (status) {
      case 401:
        errorMessage = "Authentication failed. Run `openmates login` to re-authenticate.";
        break;
      case 413:
        errorMessage = "File too large (maximum 100 MB).";
        break;
      case 415:
        errorMessage = "Unsupported file type.";
        break;
      case 422: {
        const body = await response.text().catch(() => "");
        errorMessage = body.includes("malware")
          ? "File rejected: malware detected."
          : body.includes("content_safety")
            ? "File rejected: content safety violation."
            : `Upload validation failed: ${body}`;
        break;
      }
      case 429:
        errorMessage = "Upload rate limit exceeded. Try again in a minute.";
        break;
      default:
        errorMessage = `Upload failed (HTTP ${status}).`;
    }
    throw new Error(errorMessage);
  }

  const data = (await response.json()) as UploadFileResponse;
  return data;
}
