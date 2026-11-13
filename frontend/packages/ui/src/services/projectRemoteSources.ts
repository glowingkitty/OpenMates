// frontend/packages/ui/src/services/projectRemoteSources.ts
// Pure helpers for Projects remote-source UI and service code.
// Remote previews are message-local virtual artifacts by default and must not
// create real embeds unless the user explicitly uploads them to OpenMates.
// The rules live in projectState/ (remoteFilePolicy.ts, projectRecordPolicy.ts),
// shared with the Rust core twin (web_projects); this module keeps the synchronous
// entry points the Svelte `$derived` callers need and builds the browser File.

import { defaultProjectFocus, projectSourceCreate } from "./projectState/projectRecordPolicy";
import { remoteFileUploadPlan, type RemoteFileCompleteRead, type VirtualRemoteFilePreview } from "./projectState/remoteFilePolicy";

export {
  buildVirtualRemoteFullscreenDetail,
  classifyRemotePreviewPath,
  normalizeRemoteFilePreview,
  type RemoteFileCompleteRead,
  type RemoteFilePreviewInput,
  type RemotePreviewClassification,
  type RemotePreviewKind,
  type VirtualRemoteFilePreview,
  type VirtualRemoteFullscreenDetail,
} from "./projectState/remoteFilePolicy";

export type ProjectSourceType = "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository";
export type ProjectSourceCapability = "read" | "search" | "import" | "write_request" | "run_command";
export type ProjectSourceStatus = "connected" | "offline" | "permission_required" | "revoked";
export type ProjectWriteMode = "apply_and_show" | "always_ask";
export type ProjectRemoteAccessOperation = "list" | "search" | "read_text" | "read_image_chunk" | "read_file_chunk" | "create_file" | "update_file" | "copy_entries" | "move_entries";

export interface ProjectDefaultFocus {
  focus_id: string;
  name: string;
  instructions: string;
  source: string;
}

export function buildDefaultProjectFocus(projectName: string, instructions?: string, source = "generated"): ProjectDefaultFocus {
  return defaultProjectFocus(projectName, crypto.randomUUID(), instructions, source);
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

export function buildProjectSourceCreatePayload(input: BuildProjectSourcePayloadInput): ProjectSourceCreatePayload {
  return projectSourceCreate(input) as unknown as ProjectSourceCreatePayload;
}

/** The explicit upload of a complete remote read; `plan` is the Rust answer when the caller already has one. */
export function buildRemoteFileUploadCandidate(
  input: RemoteFileUploadCandidateInput,
  plan: ReturnType<typeof remoteFileUploadPlan> = remoteFileUploadPlan(input),
): RemoteFileUploadCandidate {
  const uploadFile = new File([input.readResult.content], plan.fileName, { type: plan.mimeType });
  return { file: uploadFile, metadata: plan.metadata };
}
