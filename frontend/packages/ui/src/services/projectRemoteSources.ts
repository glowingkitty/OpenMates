// frontend/packages/ui/src/services/projectRemoteSources.ts
// Pure helpers for Projects remote-source UI and service code.
// Remote previews are message-local virtual artifacts by default and must not
// create real embeds unless the user explicitly uploads them to OpenMates.
// Keep this file browser-independent so CLI-first contract tests can run with node:test.

export type ProjectSourceType = "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository";
export type ProjectSourceCapability = "read" | "search" | "import" | "write_request";
export type ProjectSourceStatus = "connected" | "offline" | "permission_required" | "revoked";
export type ProjectWriteMode = "always_ask" | "auto_approve_safe_writes";

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
  language?: string;
  snippet: string;
  baseHash?: string;
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
      language: string;
      snippet: string;
      base_hash?: string;
    };
  };
}

const ALLOWED_SOURCE_CAPABILITIES = new Set<ProjectSourceCapability>([
  "read",
  "search",
  "import",
  "write_request",
]);

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
        language: input.language ?? "text",
        snippet: input.snippet,
        ...(input.baseHash ? { base_hash: input.baseHash } : {}),
      },
    },
  };
}
