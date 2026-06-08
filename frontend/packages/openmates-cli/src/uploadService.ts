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
import { basename, extname } from "node:path";
import type { OpenMatesSession } from "./storage.js";

const UPLOAD_MAX_ATTEMPTS = 3;
const UPLOAD_RETRY_DELAY_MS = 2_000;
const PROFILE_IMAGE_MAX_SIZE_BYTES = 300 * 1024;

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

export interface AudioTranscriptionData {
  transcript: string | null;
  transcript_original: string | null;
  transcript_corrected: string | null;
  use_corrected: boolean | null;
  correction_model: string | null;
  model: string | null;
}

interface AudioTranscriptionResponse {
  success?: boolean;
  error?: string;
  data?: {
    results?: Array<{
      id?: string;
      error?: string | null;
      results?: Array<{
        transcript?: string | null;
        transcript_original?: string | null;
        transcript_corrected?: string | null;
        use_corrected?: boolean | null;
        correction_model?: string | null;
        model?: string | null;
        error?: string | null;
      }>;
    }>;
  };
}

// ── Upload URL resolution ──────────────────────────────────────────────

/**
 * Derive the upload server URL from the API URL.
 * Both dev and prod API environments use upload.openmates.org, matching
 * frontend/packages/ui/src/config/api.ts.
 */
function getUploadUrl(apiUrl: string): string {
  try {
    const url = new URL(apiUrl);
    if (url.hostname === "localhost") return "http://localhost:8001";
  } catch {
    // Fall back to the shared cloud upload endpoint below.
  }
  return "https://upload.openmates.org";
}

function getUploadOrigin(apiUrl: string): string {
  try {
    const url = new URL(apiUrl);
    if (url.hostname === "localhost") return "http://localhost:5173";
    if (url.hostname.startsWith("api.")) {
      return `${url.protocol}//app.${url.hostname.slice(4)}`;
    }
  } catch {
    // Fall back to production app origin below.
  }
  return "https://app.openmates.org";
}

function getUploadMimeType(filename: string): string {
  const ext = extname(filename).toLowerCase();
  switch (ext) {
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".png":
      return "image/png";
    case ".webp":
      return "image/webp";
    case ".gif":
      return "image/gif";
    case ".heic":
      return "image/heic";
    case ".heif":
      return "image/heif";
    case ".bmp":
      return "image/bmp";
    case ".tif":
    case ".tiff":
      return "image/tiff";
    case ".svg":
      return "image/svg+xml";
    case ".pdf":
      return "application/pdf";
    case ".mp3":
      return "audio/mpeg";
    case ".m4a":
    case ".mp4":
      return "audio/mp4";
    case ".wav":
      return "audio/wav";
    case ".webm":
      return "audio/webm";
    case ".ogg":
    case ".oga":
      return "audio/ogg";
    case ".aac":
      return "audio/aac";
    default:
      return "application/octet-stream";
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
  const origin = getUploadOrigin(session.apiUrl);

  // Construct cookie header from session
  const cookies: string[] = [];
  if (session.cookies?.auth_refresh_token) {
    cookies.push(`auth_refresh_token=${session.cookies.auth_refresh_token}`);
  }

  let response: Response | undefined;
  let lastError: unknown;

  for (let attempt = 1; attempt <= UPLOAD_MAX_ATTEMPTS; attempt++) {
    try {
      // Build multipart form data for each attempt because request bodies may
      // be consumed even when the transport fails.
      const blob = new Blob([fileBytes], { type: getUploadMimeType(filename) });
      const formData = new FormData();
      formData.append("file", blob, filename);

      response = await fetch(uploadUrl, {
        method: "POST",
        body: formData,
        headers: {
          Origin: origin,
          ...(cookies.length > 0 ? { Cookie: cookies.join("; ") } : {}),
        },
        signal: AbortSignal.timeout(10 * 60 * 1000), // 10-minute timeout
      });
      break;
    } catch (error) {
      lastError = error;
      if (attempt === UPLOAD_MAX_ATTEMPTS) break;
      await new Promise((resolve) => setTimeout(resolve, UPLOAD_RETRY_DELAY_MS));
    }
  }

  if (!response) {
    const message = lastError instanceof Error ? lastError.message : String(lastError);
    throw new Error(message || "Upload request failed.");
  }

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

export async function transcribeUploadedAudio(
  uploadResult: UploadFileResponse,
  filename: string,
  session: OpenMatesSession,
  options: { chatId?: string; requestId?: string } = {},
): Promise<AudioTranscriptionData> {
  const s3Key =
    uploadResult.files?.original?.s3_key ??
    Object.values(uploadResult.files ?? {})[0]?.s3_key;

  if (!s3Key) {
    throw new Error("Upload succeeded but no audio file key was returned.");
  }

  const cookies: string[] = [];
  if (session.cookies?.auth_refresh_token) {
    cookies.push(`auth_refresh_token=${session.cookies.auth_refresh_token}`);
  }

  const requestItem: Record<string, unknown> = {
    id: options.requestId ?? uploadResult.embed_id,
    embed_id: uploadResult.embed_id,
    s3_key: s3Key,
    s3_base_url: uploadResult.s3_base_url,
    aes_key: uploadResult.aes_key,
    aes_nonce: uploadResult.aes_nonce,
    vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
    filename,
    mime_type: uploadResult.content_type,
  };
  if (options.chatId) {
    requestItem.chat_id = options.chatId;
  }

  const response = await fetch(
    `${session.apiUrl.replace(/\/$/, "")}/v1/apps/audio/skills/transcribe`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(cookies.length > 0 ? { Cookie: cookies.join("; ") } : {}),
      },
      body: JSON.stringify({ requests: [requestItem] }),
      signal: AbortSignal.timeout(10 * 60 * 1000),
    },
  );

  if (!response.ok) {
    let detail = `Transcription failed (HTTP ${response.status}).`;
    try {
      const data = (await response.json()) as { detail?: string; error?: string };
      detail = data.detail ?? data.error ?? detail;
    } catch {
      // Keep the status-based detail when the response body is not JSON.
    }
    throw new Error(detail);
  }

  const data = (await response.json()) as AudioTranscriptionResponse;
  if (data.success === false) {
    throw new Error(data.error ?? "Transcription failed.");
  }

  const requestId = options.requestId ?? uploadResult.embed_id;
  const group =
    data.data?.results?.find((item) => item.id === requestId) ??
    data.data?.results?.[0];
  const result = group?.results?.[0];
  if (!result) {
    throw new Error(group?.error ?? "Transcription response did not include a result.");
  }
  if (result.error) {
    throw new Error(result.error);
  }

  return {
    transcript: result.transcript ?? null,
    transcript_original: result.transcript_original ?? null,
    transcript_corrected: result.transcript_corrected ?? null,
    use_corrected: result.use_corrected ?? null,
    correction_model: result.correction_model ?? null,
    model: result.model ?? null,
  };
}

export interface ProfileImageUploadResponse {
  status: "ok" | "rejected" | "account_deleted" | string;
  url?: string;
  detail?: string;
  reject_count?: number;
}

function getProfileImageMime(filename: string): string {
  const ext = extname(filename).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  throw new Error("Profile images must be JPEG or PNG files.");
}

export async function uploadProfileImage(
  filePath: string,
  session: OpenMatesSession,
): Promise<ProfileImageUploadResponse> {
  const filename = basename(filePath);
  const fileBytes = readFileSync(filePath);
  const contentType = getProfileImageMime(filename);
  if (fileBytes.byteLength > PROFILE_IMAGE_MAX_SIZE_BYTES) {
    throw new Error("Profile image must be 300 KB or smaller. Resize/compress the image and try again.");
  }
  const uploadUrl = `${getUploadUrl(session.apiUrl)}/v1/upload/profile-image`;
  const origin = getUploadOrigin(session.apiUrl);

  const cookies: string[] = [];
  if (session.cookies?.auth_refresh_token) {
    cookies.push(`auth_refresh_token=${session.cookies.auth_refresh_token}`);
  }

  const formData = new FormData();
  formData.append("file", new Blob([fileBytes], { type: contentType }), filename);
  const response = await fetch(uploadUrl, {
    method: "POST",
    body: formData,
    headers: {
      Origin: origin,
      ...(cookies.length > 0 ? { Cookie: cookies.join("; ") } : {}),
    },
  });
  const data = (await response.json().catch(() => ({}))) as ProfileImageUploadResponse;
  if (!response.ok && !data.status) {
    throw new Error(data.detail ?? `Profile image upload failed (HTTP ${response.status}).`);
  }
  return data;
}
