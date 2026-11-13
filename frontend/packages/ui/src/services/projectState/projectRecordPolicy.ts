// frontend/packages/ui/src/services/projectState/projectRecordPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Project record decisions of projectService.ts: which key wrapper opens a Project,
// the list/entity cache merge after a mutation, create/patch/settings request plans,
// settings/source/contents view assembly after decryption, source create payloads,
// upload routing and the hosted file head checks. The page keeps fetch, the
// WorkspaceQueryCache, IndexedDB/embedStore and every AES/SHA primitive; with
// VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides (web_projects/records.rs,
// settings.rs, uploads.rs). Plaintext values come back for the page to encrypt; the
// page builds the wire bodies in their original key order. No imports (generate.mjs).

export type ProjectWriteModeValue = "apply_and_show" | "always_ask";

/** The default Project focus (`buildDefaultProjectFocus` with the id chosen by the caller). */
export function defaultProjectFocus(projectName: string, focusId: string, instructions?: string, source = "generated") {
  const name = projectName.trim() || "Untitled project";
  return {
    focus_id: focusId,
    name: `Work on ${name}`,
    instructions: instructions?.trim() || `Help with work in ${name}. Follow the user's instructions and the Project's connected source guidance.`,
    source,
  };
}

function normalizeProjectWriteMode(writeMode: unknown): ProjectWriteModeValue | null {
  return writeMode === "apply_and_show" || writeMode === "always_ask" ? writeMode : null;
}

/** `[ProjectService]` warning the page logs for unreadable decrypted metadata. */
export interface MetadataWarning { kind: "non_object" | "parse_error"; context: string }

function parseProjectMetadata(metadataText: string, context: string, warnings: MetadataWarning[]): Record<string, unknown> {
  if (!metadataText) return {};
  try {
    const parsed = JSON.parse(metadataText) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    warnings.push({ kind: "non_object", context });
    return {};
  } catch {
    warnings.push({ kind: "parse_error", context });
    return {};
  }
}

/** Which wrapper decrypts a Project for the workspace (`teamHash` = SHA-256 of the team id, null when personal). */
export function projectWrapperSelect(input: {
  teamId: string | null; teamHash: string | null; encryptedProjectKey?: string | null;
  keyWrappers?: Array<{ key_type: string; encrypted_project_key: string; hashed_team_id?: string }>;
}): { mode: "team"; wrapper: string } | { mode: "master"; encryptedProjectKey: string } | { mode: "none" } {
  const teamWrapper = input.teamHash
    ? input.keyWrappers?.find(wrapper => wrapper.key_type === "team" && wrapper.hashed_team_id === input.teamHash) : undefined;
  if (input.teamId && !teamWrapper) return { mode: "none" };
  if (teamWrapper && input.teamId) return { mode: "team", wrapper: teamWrapper.encrypted_project_key };
  return input.encryptedProjectKey ? { mode: "master", encryptedProjectKey: input.encryptedProjectKey } : { mode: "none" };
}

/**
 * Cache merge after an authoritative Project response. `current` is the cached entity
 * (or list entry) for the id, `cachedIds` the loaded summary list (null when none).
 * A newer cached version wins; otherwise the list replaces, prepends (new Projects),
 * re-sets the unchanged list (fencing a concurrent read) or is invalidated.
 */
export function projectPublishMerge(input: {
  projectId: string; incomingVersion: number | null; current: { version: number | null } | null;
  cachedIds: string[] | null; isNew: boolean;
}): { keepCurrent: true } | { keepCurrent: false; list: "replace" | "prepend" | "reset" | "invalidate" } {
  if (input.current && (input.current.version ?? 0) > (input.incomingVersion ?? 0)) return { keepCurrent: true };
  if (!input.cachedIds) return { keepCurrent: false, list: "invalidate" };
  const present = input.cachedIds.some((id) => id === input.projectId);
  return { keepCurrent: false, list: present ? "replace" : input.isNew ? "prepend" : "reset" };
}

/** Summary list after a delete: drop the id from a loaded list, else invalidate. */
export function projectDeleteMerge(input: { cachedIds: string[] | null }): { list: "filter" | "invalidate" } {
  return { list: input.cachedIds ? "filter" : "invalidate" };
}

/** Plaintexts and plain fields of a new Project; the page encrypts and posts them. */
export function projectCreatePlan(input: {
  name: string; writeMode: ProjectWriteModeValue | null; focusId: string; timestamp: number;
}) {
  const defaultFocus = defaultProjectFocus(input.name, input.focusId);
  return {
    plaintext: {
      name: input.name, description: "", icon: "folder", color: "default",
      settings: JSON.stringify({ default_focus: defaultFocus }),
    },
    fields: {
      pinned: false, created_at: input.timestamp, updated_at: input.timestamp, last_opened_at: input.timestamp,
      write_mode: input.writeMode, chat_organization_only: input.writeMode === null,
      default_focus_id: defaultFocus.focus_id,
    },
    teamKeyEpoch: 1,
  };
}

/** Optimistic-concurrency version and the fields a metadata PATCH encrypts. */
export function projectMetadataPatch(input: { version: number | null; name: boolean; description: boolean }) {
  return { version: input.version ?? 1, encryptName: input.name, encryptDescription: input.description };
}

/** Whether stored settings need the default focus initialized, and the PATCH plan when they do. */
export function projectSettingsInit(input: {
  settings: { encrypted_settings?: string | null; write_mode?: unknown }; projectName: string; focusId: string; timestamp: number;
}) {
  if (input.settings.encrypted_settings) return { init: false as const };
  const defaultFocus = defaultProjectFocus(input.projectName, input.focusId);
  return {
    init: true as const,
    settingsPlaintext: JSON.stringify({ default_focus: defaultFocus }),
    writeMode: normalizeProjectWriteMode(input.settings.write_mode) ?? "apply_and_show",
    defaultFocusId: defaultFocus.focus_id,
    updatedAt: input.timestamp,
  };
}

/** Body of a settings PATCH (only the provided settings plus `updated_at`). */
export function projectSettingsPatch(input: {
  writeMode: ProjectWriteModeValue | null; autoSelection?: boolean; focusActivationPolicy?: string; timestamp: number;
}) {
  return {
    ...(input.writeMode ? { write_mode: input.writeMode } : {}),
    ...(input.autoSelection === undefined ? {} : { auto_selection: input.autoSelection }),
    ...(input.focusActivationPolicy === undefined ? {} : { focus_activation_policy: input.focusActivationPolicy }),
    updated_at: input.timestamp,
  };
}

/** Settings view model from the stored record and its decrypted settings text. */
export function projectSettingsView(input: { settings: Record<string, unknown>; settingsText: string }) {
  const settings = input.settings;
  const warnings: MetadataWarning[] = [];
  const parsed = parseProjectMetadata(input.settingsText, "settings", warnings);
  return {
    autoSelection: settings.auto_selection !== false,
    focusActivationPolicy: settings.focus_activation_policy === "immediate" || settings.focus_activation_policy === "approval" ? settings.focus_activation_policy : "delayed",
    writeMode: normalizeProjectWriteMode(settings.write_mode),
    selectionRequired: settings.selection_required === true || normalizeProjectWriteMode(settings.write_mode) === null,
    settings: parsed,
    encrypted: { ...settings, write_mode: normalizeProjectWriteMode(settings.write_mode) },
    warnings,
  };
}

/** Source view model from the stored record and its decrypted display name / metadata. */
export function projectSourceView(input: { source: Record<string, unknown>; metadataText: string; displayName: string }) {
  const source = input.source;
  const warnings: MetadataWarning[] = [];
  const metadata = parseProjectMetadata(input.metadataText, `source:${source.source_id}`, warnings);
  return {
    source_id: source.source_id,
    source_type: source.source_type,
    displayName: input.displayName,
    metadata,
    capabilities: source.capabilities ?? [],
    status: source.status ?? "connected",
    sourceSessionId: source.source_session_id ?? null,
    keyEpoch: source.key_epoch ?? null,
    encrypted: source,
    warnings,
  };
}

const ALLOWED_SOURCE_CAPABILITIES = new Set(["read", "search", "import", "write_request"]);

/** `buildProjectSourceCreatePayload`: allowed capabilities only, default status `connected`. */
export function projectSourceCreate(input: {
  sourceId: string; sourceType: string; encryptedDisplayName: string; encryptedMetadata: string;
  capabilities?: string[]; timestamp: number; status?: string; lastIndexedAt?: number | null;
}) {
  const capabilities = (input.capabilities ?? []).filter((capability) => ALLOWED_SOURCE_CAPABILITIES.has(capability));
  const payload: Record<string, unknown> = {
    source_id: input.sourceId,
    source_type: input.sourceType,
    encrypted_display_name: input.encryptedDisplayName,
    encrypted_metadata: input.encryptedMetadata,
    capabilities,
    status: input.status ?? "connected",
    created_at: input.timestamp,
    updated_at: input.timestamp,
  };
  if (input.lastIndexedAt !== undefined) payload.last_indexed_at = input.lastIndexedAt;
  return payload;
}

/** Folder and item view models from the stored rows and their decrypted fields. */
export function projectContentsView(input: {
  folders: Array<{ record: Record<string, unknown>; name: string }>;
  items: Array<{ record: Record<string, unknown>; metadataText: string; targetId: string; displayName: string }>;
}) {
  const warnings: MetadataWarning[] = [];
  const folders = input.folders.map(({ record, name }) => ({
    folder_id: record.folder_id,
    name,
    parentHash: record.hashed_parent_folder_id ?? null,
    encrypted: record,
  }));
  const items = input.items.map(({ record, metadataText, targetId, displayName }) => ({
    project_item_id: record.project_item_id,
    item_type: record.item_type,
    target_id: targetId,
    displayName,
    metadata: parseProjectMetadata(metadataText, `item:${record.project_item_id}`, warnings),
    encrypted: record,
  }));
  return { folders, items, warnings };
}

const REMOTE_CODE_UPLOAD_EXTENSIONS = new Set([
  "c", "cpp", "css", "go", "h", "html", "java", "js", "json", "jsx", "md", "py", "rs", "svelte", "swift", "ts",
  "tsx", "txt", "yaml", "yml",
]);
const REMOTE_CODE_LANGUAGE_BY_EXTENSION: Record<string, string> = {
  c: "c", cpp: "cpp", css: "css", go: "go", h: "c", html: "html", java: "java", js: "javascript", json: "json",
  jsx: "javascript", md: "markdown", py: "python", rs: "rust", svelte: "svelte", swift: "swift", ts: "typescript",
  tsx: "typescript", txt: "text", yaml: "yaml", yml: "yaml",
};

function getFilenameExtension(filename: string): string {
  const basename = filename.toLowerCase().replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? "";
  const extensionIndex = basename.lastIndexOf(".");
  return extensionIndex > 0 ? basename.slice(extensionIndex + 1) : "";
}

/** Upload path of a Project file: inline code embed, mind map or a generic uploaded file. */
export function projectUploadRoute(input: { fileName: string; fileType: string; importedFromRemote: boolean }) {
  const lower = input.fileName.toLowerCase();
  const readme = lower === "readme.md";
  const extension = getFilenameExtension(input.fileName);
  // The Overview reads the encrypted code payload directly. A normal root README
  // upload must take this path too: generic file uploads only store media keys.
  const code = readme || (input.importedFromRemote
    && (REMOTE_CODE_UPLOAD_EXTENSIONS.has(extension) || input.fileType.startsWith("text/")));
  const route = code ? "code" : lower.endsWith(".ommindmap") || lower.endsWith(".openmates-mindmap.json") ? "mindmap" : "file";
  return { route, language: REMOTE_CODE_LANGUAGE_BY_EXTENSION[extension] ?? "text", readme };
}

/** Embed type and app id of a generic uploaded Project file. */
export function projectUploadEmbedType(input: { filename: string; contentType: string }) {
  const contentType = input.contentType || "";
  const filename = input.filename.toLowerCase();
  let embedType = "file";
  if (contentType === "application/pdf" || filename.endsWith(".pdf")) embedType = "pdf";
  else if (contentType.startsWith("image/")) embedType = "images-image";
  else if (contentType.startsWith("video/")) embedType = "video";
  else if (contentType.startsWith("audio/")) embedType = "audio";
  else if (filename.endsWith(".csv") || filename.endsWith(".tsv") || filename.endsWith(".xlsx")) embedType = "sheet";
  else if (filename.endsWith(".eml") || filename.endsWith(".msg")) embedType = "mail";
  else if (/\.(ts|tsx|js|jsx|py|swift|go|rs|java|c|cpp|h|css|html|svelte|json|yml|yaml|md)$/.test(filename)) embedType = "code-code";
  return { embedType, appId: embedType.split("-")[0] || "files" };
}

/** Project-key wrapper of a hosted file head and its revision (null when not a positive safe integer). */
export function projectFileHead(input: { embedKeys?: Array<Record<string, unknown>> | null; versionNumber?: unknown }) {
  const wrapper = input.embedKeys?.find((item) => item.key_type === "project" && typeof item.encrypted_embed_key === "string");
  const revision = Number(input.versionNumber ?? 1);
  return {
    wrapper: wrapper ? String(wrapper.encrypted_embed_key) : null,
    revision: Number.isSafeInteger(revision) && revision >= 1 ? revision : null,
  };
}

export const RECORD_OPS = {
  projectWrapperSelect, projectPublishMerge, projectDeleteMerge, projectCreatePlan, projectMetadataPatch,
  projectSettingsInit, projectSettingsPatch, projectSettingsView, projectSourceView, projectSourceCreate,
  projectContentsView, projectUploadRoute, projectUploadEmbedType, projectFileHead,
};
