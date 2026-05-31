// frontend/packages/ui/src/services/projectService.ts
// Client-side Projects V1 service.
//
// Projects use a project-specific AES key for metadata. Uploaded files are
// represented as embeds first, then linked into a project via project_items.

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
  wrapEmbedKeyWithChatKey,
  wrapEmbedKeyWithMasterKey,
} from "./cryptoService";
import { embedStore } from "./embedStore";
import { uploadFileToServer, type UploadFileResponse } from "../components/enter_message/services/uploadService";

export type ProjectItemType = "embed" | "chat" | "upload" | "workflow";

export interface EncryptedProjectRecord {
  id?: string;
  project_id: string;
  encrypted_project_key: string;
  encrypted_name: string;
  encrypted_description?: string | null;
  encrypted_icon?: string | null;
  encrypted_color?: string | null;
  pinned?: boolean;
  archived?: boolean;
  is_private?: boolean;
  is_shared?: boolean;
  created_at: number;
  updated_at: number;
  last_opened_at: number;
  item_count?: number;
}

export interface ProjectFolderRecord {
  folder_id: string;
  hashed_project_id: string;
  hashed_parent_folder_id?: string | null;
  encrypted_name: string;
  created_at: number;
  updated_at: number;
  position: number;
}

export interface ProjectItemRecord {
  hashed_folder_id?: string | null;
  project_item_id: string;
  item_type: ProjectItemType;
  target_id_hash: string;
  target_id_encrypted: string;
  encrypted_display_name?: string | null;
  encrypted_note?: string | null;
  encrypted_metadata?: string | null;
  created_at: number;
  updated_at: number;
  position: number;
}

export interface ProjectFolderViewModel {
  folder_id: string;
  name: string;
  parentHash: string | null;
  encrypted: ProjectFolderRecord;
}

export interface ProjectItemViewModel {
  project_item_id: string;
  item_type: ProjectItemType;
  target_id: string;
  displayName: string;
  metadata: Record<string, unknown>;
  encrypted: ProjectItemRecord;
}

export interface ProjectViewModel {
  project_id: string;
  name: string;
  description: string;
  projectKey: Uint8Array;
  encrypted: EncryptedProjectRecord;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(getApiEndpoint(path), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Projects API failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
}

function generateProjectKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
}

export async function decryptProject(record: EncryptedProjectRecord): Promise<ProjectViewModel | null> {
  const projectKey = await decryptChatKeyWithMasterKey(record.encrypted_project_key);
  if (!projectKey) return null;
  return {
    project_id: record.project_id,
    name: await decryptOptional(record.encrypted_name, projectKey),
    description: await decryptOptional(record.encrypted_description, projectKey),
    projectKey,
    encrypted: record,
  };
}

export async function listProjects(): Promise<ProjectViewModel[]> {
  const data = await requestJson<{ projects: EncryptedProjectRecord[] }>("/v1/projects");
  const decrypted = await Promise.all(data.projects.map(decryptProject));
  return decrypted.filter((project): project is ProjectViewModel => project !== null);
}

export async function createProject(name: string): Promise<ProjectViewModel> {
  const projectKey = generateProjectKey();
  const encryptedProjectKey = await encryptChatKeyWithMasterKey(projectKey);
  if (!encryptedProjectKey) throw new Error("Could not wrap project key with master key");
  const timestamp = nowSeconds();
  const projectId = crypto.randomUUID();
  const body = {
    project_id: projectId,
    encrypted_project_key: encryptedProjectKey,
    encrypted_name: await encryptWithEmbedKey(name, projectKey),
    encrypted_description: await encryptWithEmbedKey("", projectKey),
    encrypted_icon: await encryptWithEmbedKey("folder", projectKey),
    encrypted_color: await encryptWithEmbedKey("default", projectKey),
    pinned: false,
    created_at: timestamp,
    updated_at: timestamp,
    last_opened_at: timestamp,
  };
  const data = await requestJson<{ project: EncryptedProjectRecord }>("/v1/projects", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return (await decryptProject(data.project)) ?? {
    project_id: projectId,
    name,
    description: "",
    projectKey,
    encrypted: data.project,
  };
}

export async function deleteProject(projectId: string): Promise<void> {
  await requestJson<{ deleted: boolean }>(`/v1/projects/${projectId}`, { method: "DELETE" });
}

export async function getProjectContents(project: ProjectViewModel): Promise<{
  folders: ProjectFolderViewModel[];
  items: ProjectItemViewModel[];
}> {
  const data = await requestJson<{ folders: ProjectFolderRecord[]; items: ProjectItemRecord[] }>(
    `/v1/projects/${project.project_id}/items`,
  );
  const folders = await Promise.all(
    data.folders.map(async (folder) => ({
      folder_id: folder.folder_id,
      name: await decryptOptional(folder.encrypted_name, project.projectKey),
      parentHash: folder.hashed_parent_folder_id ?? null,
      encrypted: folder,
    })),
  );
  const items = await Promise.all(
    data.items.map(async (item) => {
      const metadataText = await decryptOptional(item.encrypted_metadata, project.projectKey);
      let metadata: Record<string, unknown> = {};
      try {
        metadata = metadataText ? JSON.parse(metadataText) : {};
      } catch {
        metadata = {};
      }
      return {
        project_item_id: item.project_item_id,
        item_type: item.item_type,
        target_id: await decryptOptional(item.target_id_encrypted, project.projectKey),
        displayName: await decryptOptional(item.encrypted_display_name, project.projectKey),
        metadata,
        encrypted: item,
      };
    }),
  );
  return { folders, items };
}

export async function createFolder(project: ProjectViewModel, name: string, parentFolderId?: string): Promise<void> {
  const timestamp = nowSeconds();
  await requestJson(`/v1/projects/${project.project_id}/folders`, {
    method: "POST",
    body: JSON.stringify({
      folder_id: crypto.randomUUID(),
      parent_folder_id: parentFolderId ?? null,
      encrypted_name: await encryptWithEmbedKey(name, project.projectKey),
      encrypted_sort_key: await encryptWithEmbedKey(name.toLowerCase(), project.projectKey),
      created_at: timestamp,
      updated_at: timestamp,
      position: timestamp,
    }),
  });
}

export async function addExistingTargetToProject(
  project: ProjectViewModel,
  targetId: string,
  itemType: ProjectItemType,
  displayName: string,
  folderId?: string,
): Promise<void> {
  const timestamp = nowSeconds();
  await requestJson(`/v1/projects/${project.project_id}/items`, {
    method: "POST",
    body: JSON.stringify({
      project_item_id: crypto.randomUUID(),
      folder_id: folderId ?? null,
      item_type: itemType,
      target_id: targetId,
      target_id_encrypted: await encryptWithEmbedKey(targetId, project.projectKey),
      encrypted_display_name: await encryptWithEmbedKey(displayName, project.projectKey),
      encrypted_note: await encryptWithEmbedKey("", project.projectKey),
      encrypted_metadata: await encryptWithEmbedKey("{}", project.projectKey),
      created_at: timestamp,
      updated_at: timestamp,
      position: timestamp,
    }),
  });
}

function embedTypeForUpload(upload: UploadFileResponse): string {
  const contentType = upload.content_type || "";
  const filename = upload.filename.toLowerCase();
  if (contentType === "application/pdf" || filename.endsWith(".pdf")) return "pdf";
  if (contentType.startsWith("image/")) return "images-image";
  if (contentType.startsWith("video/")) return "video";
  if (contentType.startsWith("audio/")) return "audio";
  if (filename.endsWith(".csv") || filename.endsWith(".tsv") || filename.endsWith(".xlsx")) return "sheet";
  if (filename.endsWith(".eml") || filename.endsWith(".msg")) return "mail";
  if (/\.(ts|tsx|js|jsx|py|swift|go|rs|java|c|cpp|h|css|html|svelte|json|yml|yaml|md)$/.test(filename)) return "code-code";
  return "file";
}

export async function uploadFileToProject(project: ProjectViewModel, file: File): Promise<void> {
  const upload = await uploadFileToServer(file);
  const timestampMs = Date.now();
  const timestamp = Math.floor(timestampMs / 1000);
  const embedKey = generateEmbedKey();
  const embedType = embedTypeForUpload(upload);
  const embedContent = JSON.stringify({
    app_id: embedType.split("-")[0] || "files",
    skill_id: "upload",
    type: embedType,
    status: "finished",
    filename: upload.filename,
    file_size: file.size,
    file_type: upload.content_type,
    content_hash: upload.content_hash,
    s3_base_url: upload.s3_base_url,
    files: upload.files,
    aes_key: upload.aes_key,
    aes_nonce: upload.aes_nonce,
    vault_wrapped_aes_key: upload.vault_wrapped_aes_key,
    page_count: upload.page_count ?? null,
    ai_detection: upload.ai_detection,
  });
  const hashedEmbedId = await computeSHA256(upload.embed_id);
  const hashedProjectId = await computeSHA256(project.project_id);
  const wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKey);
  const wrappedProjectKey = await wrapEmbedKeyWithChatKey(embedKey, project.projectKey);
  if (!wrappedMasterKey || !wrappedProjectKey) throw new Error("Could not wrap upload embed keys");

  await requestJson(`/v1/projects/${project.project_id}/upload-embed`, {
    method: "POST",
    body: JSON.stringify({
      embed: {
        embed_id: upload.embed_id,
        encrypted_type: await encryptWithEmbedKey(embedType, embedKey),
        status: "finished",
        encrypted_content: await encryptWithEmbedKey(embedContent, embedKey),
        encrypted_text_preview: await encryptWithEmbedKey(upload.filename, embedKey),
        content_hash: upload.content_hash,
        created_at: timestamp,
        updated_at: timestamp,
        encryption_mode: "client",
        is_private: true,
        is_shared: false,
      },
      embed_keys: [
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "master",
          encrypted_embed_key: wrappedMasterKey,
          created_at: timestamp,
        },
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "project",
          hashed_project_id: hashedProjectId,
          encrypted_embed_key: wrappedProjectKey,
          created_at: timestamp,
        },
      ],
      item: {
        project_item_id: crypto.randomUUID(),
        item_type: "embed",
        target_id: upload.embed_id,
        target_id_encrypted: await encryptWithEmbedKey(upload.embed_id, project.projectKey),
        encrypted_display_name: await encryptWithEmbedKey(upload.filename, project.projectKey),
        encrypted_note: await encryptWithEmbedKey("", project.projectKey),
        encrypted_metadata: await encryptWithEmbedKey(JSON.stringify({ embed_type: embedType }), project.projectKey),
        created_at: timestamp,
        updated_at: timestamp,
        position: timestamp,
      },
    }),
  });

  await embedStore.put(
    `embed:${upload.embed_id}`,
    {
      embed_id: upload.embed_id,
      type: embedType as never,
      status: "finished",
      content: embedContent,
      text_preview: upload.filename,
      createdAt: timestampMs,
      updatedAt: timestampMs,
    },
    embedType as never,
  );
}
