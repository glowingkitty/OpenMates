// frontend/packages/ui/src/services/projectRemoteSources.ts
// Pure helpers for Projects remote-source UI and service code.
// Remote previews are message-local virtual artifacts by default and must not
// create real embeds unless the user explicitly uploads them to OpenMates.
// Keep this file browser-independent so CLI-first contract tests can run with node:test.

export type ProjectSourceType = "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository";
export type ProjectSourceCapability = "read" | "search" | "import" | "write_request" | "run_command";
export type ProjectSourceStatus = "connected" | "offline" | "permission_required" | "revoked";
export type ProjectWriteMode = "apply_and_show" | "always_ask";
export type ProjectRemoteAccessOperation = "list" | "search" | "read_text" | "create_file" | "update_file";

export interface ProjectDefaultFocus {
  focus_id: string;
  name: string;
  instructions: string;
  source: string;
}

export function buildDefaultProjectFocus(projectName: string, instructions?: string, source = "generated"): ProjectDefaultFocus {
  const name = projectName.trim() || "Untitled project";
  return {
    focus_id: crypto.randomUUID(),
    name: `Work on ${name}`,
    instructions: instructions?.trim() || `Help with work in ${name}. Follow the user's instructions and the Project's connected source guidance.`,
    source,
  };
}

export interface ProjectSourceCreatePayload {
  source_id: string;
  source_type: ProjectSourceType;
  encrypted_display_name: string;
  encrypted_metadata: string;
  capabilities: ProjectSourceCapability[];
  status: ProjectSourceStatus;
  created_at: number;
  updated_at: number;
  last_indexed_at?: number | null;
}

export interface BuildProjectSourcePayloadInput {
  sourceId: string;
  sourceType: ProjectSourceType;
  encryptedDisplayName: string;
  encryptedMetadata: string;
  capabilities?: string[];
  timestamp: number;
  status?: ProjectSourceStatus;
  lastIndexedAt?: number | null;
}

export interface RemoteFilePreviewInput {
  sourceId: string;
  path: string;
  displayName: string;
  remoteItemId?: string;
  kind?: "file" | "folder";
  language?: string;
  snippet: string;
  snippetTruncated?: boolean;
  baseHash?: string;
  sizeBytes?: number;
  lineCount?: number;
  mtime?: string;
  contentHash?: string;
  gitStatus?: string;
  previewPolicy?: string;
  safetyFlags?: string[];
}

export interface VirtualRemoteFilePreview {
  isVirtual: true;
  persistAsEmbed: false;
  embed: {
    embed_id: string;
    type: "code-code";
    status: "finished";
    content: {
      type: "remote_file_preview";
      source_id: string;
        path: string;
        display_name: string;
        remote_item_id?: string;
        kind: "file" | "folder";
        language: string;
        snippet: string;
        snippet_truncated: boolean;
        base_hash?: string;
        size_bytes?: number;
        line_count?: number;
        mtime?: string;
        content_hash?: string;
        git_status?: string;
        preview_policy?: string;
        safety_flags: string[];
      };
  };
}

export interface RemoteFileUploadCandidate {
  file: File;
  metadata: {
    source_id: string;
    remote_path: string;
    remote_base_hash?: string;
    remote_content_hash?: string;
    remote_mtime?: string;
    remote_git_status?: string;
    safety_flags: string[];
    imported_from_remote_source: true;
  };
}

export interface RemoteFileUploadCandidateInput {
  preview: VirtualRemoteFilePreview;
  readResult: RemoteFileCompleteRead;
}

export interface RemoteFileCompleteRead {
  content: string;
  truncated: boolean;
  expectedBase: string | null;
}

export interface VirtualRemoteFullscreenDetail {
  embedId: string;
  embedData: VirtualRemoteFilePreview["embed"] & { app_id: "code"; skill_id: "code" };
  decodedContent: VirtualRemoteFilePreview["embed"]["content"] & {
    app_id: "code";
    skill_id: "code";
    code: string;
    filename: string;
    line_count?: number;
  };
  embedType: "code-code";
  attrs: {
    type: "code-code";
    contentRef: string;
    status: "finished";
    virtual: true;
  };
}

const ALLOWED_SOURCE_CAPABILITIES = new Set<ProjectSourceCapability>([
  "read",
  "search",
  "import",
  "write_request",
]);
const MAX_REMOTE_PREVIEW_SNIPPET_CHARS = 20_000;
const MAX_REMOTE_PREVIEW_FIELD_CHARS = 1_024;
const MAX_REMOTE_PREVIEW_POLICY_CHARS = 128;
const MAX_REMOTE_PREVIEW_SAFETY_FLAGS = 20;
const MAX_SAFE_UPLOAD_FILENAME_CHARS = 180;

export type RemotePreviewKind = "code" | "text" | "markdown" | "json" | "unsupported";

export interface RemotePreviewClassification {
  kind: RemotePreviewKind;
  language: string;
  reason?: string;
}

const REMOTE_CODE_LANGUAGE_BY_EXTENSION: Record<string, string> = {
  c: "c", cpp: "cpp", css: "css", go: "go", h: "c", html: "html", java: "java",
  js: "javascript", jsx: "javascript", py: "python", rs: "rust", sh: "bash", sql: "sql",
  svelte: "svelte", swift: "swift", toml: "toml", ts: "typescript", tsx: "typescript",
  xml: "xml", yaml: "yaml", yml: "yaml",
};
const REMOTE_BINARY_PREVIEW_EXTENSIONS = new Set([
  "7z", "avi", "bin", "bmp", "dmg", "doc", "docx", "dylib", "exe", "gif", "gz", "ico", "jar",
  "jpeg", "jpg", "mov", "mp3", "mp4", "odt", "pdf", "png", "ppt", "pptx", "rar", "so", "tar",
  "ttf", "wasm", "webm", "webp", "woff", "woff2", "xls", "xlsx", "zip",
]);

export function classifyRemotePreviewPath(path: string): RemotePreviewClassification {
  const name = path.replace(/\\/g, "/").split("/").pop()?.toLowerCase() ?? "";
  const extension = name.includes(".") ? name.split(".").pop() ?? "" : "";
  if (extension === "md" || extension === "mdx") return { kind: "markdown", language: "markdown" };
  if (extension === "json" || extension === "jsonl") return { kind: "json", language: "json" };
  if (extension === "txt" || extension === "log" || extension === "csv") return { kind: "text", language: "text" };
  if (name === "dockerfile") return { kind: "code", language: "dockerfile" };
  if (name === "makefile") return { kind: "code", language: "makefile" };
  const language = REMOTE_CODE_LANGUAGE_BY_EXTENSION[extension];
  if (language) return { kind: "code", language };
  if (REMOTE_BINARY_PREVIEW_EXTENSIONS.has(extension)) {
    return { kind: "unsupported", language: "text", reason: "This file type does not have a text preview" };
  }
  return { kind: "text", language: "text" };
}

export function buildProjectSourceCreatePayload(input: BuildProjectSourcePayloadInput): ProjectSourceCreatePayload {
  const capabilities = (input.capabilities ?? [])
    .filter((capability): capability is ProjectSourceCapability => ALLOWED_SOURCE_CAPABILITIES.has(capability as ProjectSourceCapability));
  const payload: ProjectSourceCreatePayload = {
    source_id: input.sourceId,
    source_type: input.sourceType,
    encrypted_display_name: input.encryptedDisplayName,
    encrypted_metadata: input.encryptedMetadata,
    capabilities,
    status: input.status ?? "connected",
    created_at: input.timestamp,
    updated_at: input.timestamp,
  };
  if (input.lastIndexedAt !== undefined) {
    payload.last_indexed_at = input.lastIndexedAt;
  }
  return payload;
}

export function normalizeRemoteFilePreview(input: RemoteFilePreviewInput): VirtualRemoteFilePreview {
  validateRemoteFilePreviewInput(input);
  return {
    isVirtual: true,
    persistAsEmbed: false,
    embed: {
      embed_id: `remote:${input.sourceId}:${input.path}`,
      type: "code-code",
      status: "finished",
      content: {
        type: "remote_file_preview",
        source_id: input.sourceId,
        path: input.path,
        display_name: input.displayName,
        ...(input.remoteItemId ? { remote_item_id: input.remoteItemId } : {}),
        kind: input.kind ?? "file",
        language: input.language ?? "text",
        snippet: input.snippet,
        snippet_truncated: input.snippetTruncated === true,
        ...(input.baseHash ? { base_hash: input.baseHash } : {}),
        ...(input.sizeBytes !== undefined ? { size_bytes: input.sizeBytes } : {}),
        ...(input.lineCount !== undefined ? { line_count: input.lineCount } : {}),
        ...(input.mtime ? { mtime: input.mtime } : {}),
        ...(input.contentHash ? { content_hash: input.contentHash } : {}),
        ...(input.gitStatus ? { git_status: input.gitStatus } : {}),
        ...(input.previewPolicy ? { preview_policy: input.previewPolicy } : {}),
        safety_flags: input.safetyFlags ?? [],
      },
    },
  };
}

function validateRemoteFilePreviewInput(input: RemoteFilePreviewInput): void {
  assertNonEmptyBoundedString(input.sourceId, "sourceId", MAX_REMOTE_PREVIEW_FIELD_CHARS);
  assertNonEmptyBoundedString(input.path, "path", MAX_REMOTE_PREVIEW_FIELD_CHARS);
  assertNonEmptyBoundedString(input.displayName, "displayName", MAX_REMOTE_PREVIEW_FIELD_CHARS);
  assertBoundedString(input.remoteItemId, "remoteItemId", MAX_REMOTE_PREVIEW_FIELD_CHARS);
  assertBoundedString(input.language, "language", MAX_REMOTE_PREVIEW_POLICY_CHARS);
  assertBoundedString(input.baseHash, "baseHash", MAX_REMOTE_PREVIEW_FIELD_CHARS);
  assertBoundedString(input.mtime, "mtime", MAX_REMOTE_PREVIEW_POLICY_CHARS);
  assertBoundedString(input.contentHash, "contentHash", MAX_REMOTE_PREVIEW_FIELD_CHARS);
  assertBoundedString(input.gitStatus, "gitStatus", MAX_REMOTE_PREVIEW_POLICY_CHARS);
  assertBoundedString(input.previewPolicy, "previewPolicy", MAX_REMOTE_PREVIEW_POLICY_CHARS);
  if (input.snippet.length > MAX_REMOTE_PREVIEW_SNIPPET_CHARS) {
    throw new Error("Remote preview snippet exceeds the bounded preview limit");
  }
  assertOptionalNonNegativeInteger(input.sizeBytes, "sizeBytes");
  assertOptionalNonNegativeInteger(input.lineCount, "lineCount");
  if ((input.safetyFlags?.length ?? 0) > MAX_REMOTE_PREVIEW_SAFETY_FLAGS) {
    throw new Error("Remote preview safety flags exceed the bounded metadata limit");
  }
  for (const flag of input.safetyFlags ?? []) {
    assertNonEmptyBoundedString(flag, "safetyFlag", MAX_REMOTE_PREVIEW_POLICY_CHARS);
  }
}

function assertNonEmptyBoundedString(value: string, field: string, maxLength: number): void {
  if (!value || value.length > maxLength) {
    throw new Error(`Remote preview ${field} is missing or exceeds the bounded metadata limit`);
  }
}

function assertBoundedString(value: string | undefined, field: string, maxLength: number): void {
  if (value !== undefined && value.length > maxLength) {
    throw new Error(`Remote preview ${field} exceeds the bounded metadata limit`);
  }
}

function assertOptionalNonNegativeInteger(value: number | undefined, field: string): void {
  if (value !== undefined && (!Number.isInteger(value) || value < 0)) {
    throw new Error(`Remote preview ${field} must be a non-negative integer`);
  }
}

export function buildRemoteFileUploadCandidate(input: RemoteFileUploadCandidateInput): RemoteFileUploadCandidate {
  const preview = input.preview;
  const content = preview.embed.content;
  if (input.readResult.truncated || !input.readResult.expectedBase
    || !/^[a-f0-9]{64}$/.test(input.readResult.expectedBase)) {
    throw new Error("Remote file import requires complete, non-truncated content");
  }
  const metadataMatchesRead = content.base_hash === input.readResult.expectedBase;
  const mimeType = content.language ? `text/x-${content.language}` : "text/plain";
  const uploadFile = new File([input.readResult.content], safeUploadFileName(content.display_name), { type: mimeType });
  return {
    file: uploadFile,
    metadata: {
      source_id: content.source_id,
      remote_path: content.path,
      remote_base_hash: input.readResult.expectedBase,
      ...(metadataMatchesRead && content.content_hash ? { remote_content_hash: content.content_hash } : {}),
      ...(metadataMatchesRead && content.mtime ? { remote_mtime: content.mtime } : {}),
      ...(metadataMatchesRead && content.git_status ? { remote_git_status: content.git_status } : {}),
      safety_flags: content.safety_flags,
      imported_from_remote_source: true,
    },
  };
}

function safeUploadFileName(displayName: string): string {
  const basename = displayName.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? "remote-file.txt";
  const sanitized = Array.from(basename, (character) => {
    const code = character.charCodeAt(0);
    if (
      code < 32 ||
      code === 127 ||
      (code >= 0x202a && code <= 0x202e) ||
      (code >= 0x2066 && code <= 0x2069) ||
      '<>:"/\\|?*'.includes(character)
    ) return "_";
    return character;
  }).join("").trim();
  if (!sanitized || sanitized === "." || sanitized === "..") return "remote-file.txt";
  return sanitized.slice(0, MAX_SAFE_UPLOAD_FILENAME_CHARS);
}

export function buildVirtualRemoteFullscreenDetail(
  preview: VirtualRemoteFilePreview,
  fullContent: string,
): VirtualRemoteFullscreenDetail {
  const contentRef = `remote:${preview.embed.content.source_id}:${preview.embed.content.path}`;
  return {
    embedId: preview.embed.embed_id,
    embedData: {
      ...preview.embed,
      app_id: "code",
      skill_id: "code",
    },
    decodedContent: {
      ...preview.embed.content,
      app_id: "code",
      skill_id: "code",
      code: fullContent,
      filename: preview.embed.content.display_name,
      ...(preview.embed.content.line_count !== undefined ? { line_count: preview.embed.content.line_count } : {}),
    },
    embedType: "code-code",
    attrs: {
      type: "code-code",
      contentRef,
      status: "finished",
      virtual: true,
    },
  };
}
