// frontend/packages/ui/src/services/projectState/remoteAccessPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Project source remote-access decisions of projectService.ts: request preflight,
// copy/move path validation, ignored-read approval match, relay acknowledgement and
// Team routing checks, the encrypted response verdict, result normalization and
// HTTP status mapping. Fetch, polling, X25519/AES crypto and AbortSignal stay in
// projectService.ts; with VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides
// (web_projects/remote_access.rs). No imports: generate.mjs loads this file in Node.

/** A typed refusal the adapter rethrows as `ProjectRemoteAccessError(code, message)`. */
export interface RemoteRefusal { remoteError: { code: string; message: string } }

export const PROJECT_BROWSER_REMOTE_READ_MAX_BYTES = 180 * 1024;
export const PROJECT_BROWSER_REMOTE_READ_MAX_LINES = 4_000;

const refuse = (code: string, message: string): RemoteRefusal => ({ remoteError: { code, message } });

export function projectRemotePreflight(input: {
  status: string; capabilities: string[]; operation: string; args: Record<string, unknown>; hasOwner: boolean;
}): RemoteRefusal | { userFileTransfer: boolean; readLimits: { max_bytes: number; max_lines: number } | null } {
  const { status, capabilities, operation, args } = input;
  if (status !== "connected") return refuse("source_offline", "This Project source is offline");
  if (operation === "search" && args.include_content === true && !capabilities.includes("read")) {
    return refuse("source_capability_denied", "This Project source does not allow file reads");
  }
  if (!input.hasOwner) return refuse("requester_identity_unavailable", "Authenticated user identity is unavailable");
  const userFileTransfer = operation === "copy_entries" || operation === "move_entries";
  if (userFileTransfer && (args.user_initiated !== true || !capabilities.includes("write_request"))) {
    return refuse("source_capability_denied", "This source does not allow file changes");
  }
  return {
    userFileTransfer,
    readLimits: operation === "read_text"
      ? { max_bytes: PROJECT_BROWSER_REMOTE_READ_MAX_BYTES, max_lines: PROJECT_BROWSER_REMOTE_READ_MAX_LINES }
      : null,
  };
}

export function projectRemoteTransfer(input: { paths: unknown; destinationPath: string }): RemoteRefusal | { ok: true } {
  const strictPath = (value: string) => typeof value === "string" && value.length > 0 && value.length <= 4096
    && !value.startsWith("/") && !value.includes("\\")
    && value.split("/").every((part) => part.length > 0 && part !== "." && part !== ".." && !part.startsWith("."))
    && ![...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127);
  const paths = input.paths as string[];
  if (!Array.isArray(paths) || paths.length < 1 || paths.length > 20
    || new Set(paths).size !== paths.length || !paths.every(strictPath)
    || (input.destinationPath !== "." && !strictPath(input.destinationPath))) {
    return refuse("invalid_path", "Select up to 20 files or folders within this Project");
  }
  return { ok: true };
}

export function projectIgnoredRead(input: {
  operation: string; path: unknown; approved: { path: string; chatId: string; operationId: string };
}): { ok: true } {
  const approved = input.approved;
  if (input.operation !== "read_text" || input.path !== approved.path || !approved.chatId || !approved.operationId) {
    throw new Error("The ignored-file approval does not match this exact read");
  }
  return { ok: true };
}

export function projectRemoteCreated(input: {
  created: { source_session_id?: string; key_epoch?: number }; sourceSessionId: string; keyEpoch: number;
}): RemoteRefusal | { ok: true } {
  const created = input.created;
  if ((created.source_session_id && created.source_session_id !== input.sourceSessionId)
    || (created.key_epoch && created.key_epoch !== input.keyEpoch)) {
    return refuse("source_session_changed", "The Project source session changed. Retry the request");
  }
  return { ok: true };
}

export function projectRoutingCreated(input: {
  created: { source_session_id?: string; key_epoch?: number; routing_identity?: { context_type?: string } };
}): RemoteRefusal | { ok: true } {
  const created = input.created;
  if (!created.source_session_id || !created.key_epoch || created.routing_identity?.context_type !== "team") {
    return refuse("routing_identity_unavailable", "The Team source routing identity is unavailable");
  }
  return { ok: true };
}

function parseRemoteObject(value: unknown, errorMessage: string): Record<string, unknown> {
  try {
    const parsed = typeof value === "string" ? (JSON.parse(value) as unknown) : value;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch {
    // Stable caller-facing error below.
  }
  throw new Error(errorMessage);
}

export function projectRoutingResult(input: { discovery: string | null; nonce: string }): RemoteRefusal | { ok: true } {
  const discovery = parseRemoteObject(input.discovery, "The Team source routing response is invalid");
  if (discovery.type !== "routing_discovery_result" || discovery.nonce !== input.nonce) {
    return refuse("routing_identity_invalid", "The Team source routing response is invalid");
  }
  return { ok: true };
}

function remoteAccessErrorMessage(code: string | undefined): string {
  const messages: Record<string, string> = {
    protected_path: "This file is protected or ignored",
    unsupported_file: "This file is binary or unsupported",
    invalid_path: "This source path is unavailable",
    search_query_required: "Enter a search query",
    operation_failed: "The remote source could not complete this request",
    file_changed: "The file changed. Read its current content and rebuild the edit",
    target_exists: "The create target already exists; its content was preserved",
    source_missing: "The source is gone. Check the destination before trying again",
    invalid_patch: "The patch does not exactly match the current file",
    operation_conflict: "This operation identity was already used for different changes",
    operation_unconfirmed: "A previous file operation may be incomplete. Inspect the destination before retrying",
    write_authorization_denied: "The originating chat no longer has permission to write this Project",
    ignored_path_requires_approval: "This ignored file requires explicit approval",
  };
  return messages[code ?? ""] ?? "The remote source rejected this request";
}

/** Verdict of the decrypted result document: `{result}` (absent when the source sent none) or a refusal. */
export function projectRemoteResponse(input: { plaintext: string }): RemoteRefusal | { result?: unknown } {
  const response = parseRemoteObject(input.plaintext, "The Project source returned an invalid encrypted response") as {
    ok?: boolean; result?: unknown; error?: string;
  };
  if (response.ok !== true) {
    const code = typeof response.error === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(response.error) ? response.error : "operation_failed";
    return refuse(code, remoteAccessErrorMessage(code));
  }
  return { result: response.result };
}

function normalizeProjectRemoteTextResult(value: unknown) {
  const result = parseRemoteObject(value, "The Project source returned an invalid text result");
  const expectedBase = result.expected_base;
  if (
    typeof result.content !== "string" ||
    typeof result.truncated !== "boolean" ||
    typeof result.sizeBytes !== "number" ||
    !Number.isSafeInteger(result.sizeBytes) ||
    result.sizeBytes < 0 ||
    typeof result.lineCount !== "number" ||
    !Number.isSafeInteger(result.lineCount) ||
    result.lineCount < 0 ||
    !(expectedBase === null || (typeof expectedBase === "string" && /^[a-f0-9]{64}$/.test(expectedBase)))
  ) {
    throw new Error("The Project source returned an invalid text result");
  }
  if (result.truncated && expectedBase !== null) {
    throw new Error("The Project source returned an invalid text result");
  }
  return {
    content: result.content,
    truncated: result.truncated,
    sizeBytes: result.sizeBytes,
    lineCount: result.lineCount,
    expectedBase: expectedBase as string | null,
  };
}

function normalizeProjectRemoteImageChunkResult(value: unknown): Record<string, unknown> {
  const result = parseRemoteObject(value, "The Project source returned an invalid image chunk");
  if (typeof result.content_base64 !== "string" || result.content_base64.length > 175_000
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(result.content_base64)
    || !["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"].includes(String(result.mime_type))
    || typeof result.size_bytes !== "number" || !Number.isSafeInteger(result.size_bytes)
    || result.size_bytes <= 0 || result.size_bytes > 2 * 1024 * 1024
    || typeof result.offset !== "number" || !Number.isSafeInteger(result.offset)
    || result.offset < 0 || result.offset >= result.size_bytes || result.offset % (128 * 1024) !== 0
    || typeof result.content_hash !== "string" || !/^[a-f0-9]{64}$/.test(result.content_hash)) {
    throw new Error("The Project source returned an invalid image chunk");
  }
  return result;
}

function normalizeProjectRemoteFileChunkResult(value: unknown): Record<string, unknown> {
  const result = parseRemoteObject(value, "The Project source returned an invalid file chunk");
  if (typeof result.content_base64 !== "string" || result.content_base64.length > 175_000
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(result.content_base64)
    || typeof result.size_bytes !== "number" || !Number.isSafeInteger(result.size_bytes)
    || result.size_bytes < 0
    || typeof result.offset !== "number" || !Number.isSafeInteger(result.offset)
    || result.offset < 0 || (result.size_bytes > 0 && result.offset >= result.size_bytes)
    || result.offset % (128 * 1024) !== 0
    || typeof result.file_identity !== "string" || !/^[a-f0-9]{64}$/.test(result.file_identity)
    || typeof result.chunk_hash !== "string" || !/^[a-f0-9]{64}$/.test(result.chunk_hash)) {
    throw new Error("The Project source returned an invalid file chunk");
  }
  return result;
}

/** Operations whose opened result has an operation-specific shape check. */
export const PROJECT_REMOTE_CHECKED_OPERATIONS = ["read_text", "read_image_chunk", "read_file_chunk"];

/**
 * Operation-specific shape check of an opened result. Only the checked operations
 * reach this rule; any other operation's result is used unchanged by the page.
 */
export function projectRemoteNormalize(input: { operation: string; value: unknown }): { result: unknown } {
  const { operation, value } = input;
  if (operation === "read_text") return { result: normalizeProjectRemoteTextResult(value) };
  if (operation === "read_image_chunk") return { result: normalizeProjectRemoteImageChunkResult(value) };
  if (operation === "read_file_chunk") return { result: normalizeProjectRemoteFileChunkResult(value) };
  throw new Error("The Project source operation has no result check");
}

/** HTTP failure of a relay request; `detail` is the parsed 409 body detail when one was read. */
export function projectRemoteHttpError(input: { status: number; detail?: unknown }): RemoteRefusal {
  const { status } = input;
  // A valid login can outlive its server-side per-session device binding.
  // Only this exact backend code asks the user to establish a new login.
  if (status === 409 && input.detail === "REQUESTER_DEVICE_IDENTITY_UNAVAILABLE") {
    return refuse("requester_device_identity_unavailable", "Sign out and sign in again to reconnect this Project source");
  }
  if (status === 401 || status === 403) return refuse("access_revoked", "You no longer have access to this Project source");
  if (status === 404) return refuse("source_offline", "This Project source is unavailable");
  if (status === 409) return refuse("source_offline", "This Project source changed or disconnected. Refresh and try again");
  if (status === 429) return refuse("rate_limited", "Too many Project source requests. Try again shortly");
  return refuse("operation_failed", "The Project source request failed");
}

export const REMOTE_ACCESS_OPS = {
  projectRemotePreflight, projectRemoteTransfer, projectIgnoredRead, projectRemoteCreated,
  projectRoutingCreated, projectRoutingResult, projectRemoteResponse, projectRemoteNormalize, projectRemoteHttpError,
};
