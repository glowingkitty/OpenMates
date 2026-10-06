/** Read-only Project workspace data and presentation for the terminal UI. */
import { createHash, randomBytes, randomUUID } from "node:crypto";
import type { OpenMatesClient, ProjectItemRecord, ProjectRecord, ProjectSourceRecord, TeamContextOptions } from "./client.js";
import { decryptWithAesGcmCombined, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "./crypto.js";
import { buildEncryptedObjectSlugMetadata } from "./objectSlugs.js";
import { requestProjectRemoteOperation } from "./projectRequester.js";
import { isProtectedProjectReadPath } from "../../ui/src/utils/projectSearchProtocol.js";
import { formValue, type TuiForm } from "./tuiForms.js";
import { cells, padCells, terminalText, truncateCells, type TuiLine } from "./tuiText.js";
import { centeredCarouselText, renderCardCarousel } from "./tuiCarousel.js";
import { APP_GRADIENTS, PRIMARY_GRADIENT } from "../../appGradientTheme.js";

export interface TuiProjectFile {
  id: string;
  name: string;
  path: string;
  kind: "stored" | "remote" | "folder";
  folderId?: string;
  sourceId?: string;
  embedId?: string;
}

export interface TuiProjectFolder {
  id: string;
  name: string;
  parentId?: string;
  parentHash?: string;
}

export interface TuiProjectItem {
  id: string;
  type: ProjectItemRecord["item_type"];
  name: string;
  targetId: string;
  folderId?: string;
}

export interface TuiProjectSource {
  id: string;
  name: string;
  status: string;
  type: ProjectSourceRecord["source_type"];
}

export interface TuiProject {
  id: string;
  slug: string;
  name: string;
  description: string;
  readme: string;
  icon: string;
  color: string;
  pinned: boolean;
  archived: boolean;
  itemCount?: number;
  createdAt?: number | null;
  files: TuiProjectFile[];
  folders: TuiProjectFolder[];
  items: TuiProjectItem[];
  sources: TuiProjectSource[];
  projectKey: Uint8Array;
  teamId: string | null;
  /** Kept for encrypted requester calls; never passed to a renderer. */
  sourceRecords: ProjectSourceRecord[];
}

function contextFor(client: OpenMatesClient, project?: TuiProject): TeamContextOptions {
  const teamId = project ? project.teamId : client.getActiveTeamId();
  return teamId ? { teamId } : { personal: true };
}

async function decryptField(value: unknown, key: Uint8Array): Promise<string> {
  if (typeof value !== "string" || !value) return "";
  const plain = await decryptWithAesGcmCombined(value, key);
  if (plain === null) throw new Error("Unable to decrypt Project metadata.");
  return plain;
}

function safeText(value: string): string {
  return terminalText(value).replace(/\s+/g, " ").trim();
}

function clip(value: string, width: number): string {
  return truncateCells(safeText(value), Math.max(0, width));
}

function safeFilePath(value: string): string {
  if (!value || value.length > 4096 || value.includes("\\") || /[\x00-\x1f\x7f]/.test(value) // eslint-disable-line no-control-regex -- Reject control bytes in file paths.
    || value.startsWith("/") || /^[a-z]:/i.test(value)
    || value.split("/").some((part) => !part || part === "." || part === ".." || part === ".git")
    || isProtectedProjectReadPath(value)) {
    throw new Error("Project file path is unavailable.");
  }
  return value;
}

async function projectFromRecord(client: OpenMatesClient, record: ProjectRecord, context: TeamContextOptions): Promise<TuiProject> {
  const projectKey = await client.decryptProjectKey(record, context);
  return {
    id: record.project_id,
    slug: await decryptField(record.encrypted_slug, projectKey),
    name: await decryptField(record.encrypted_name, projectKey) || "(untitled project)",
    description: await decryptField(record.encrypted_description, projectKey),
    readme: await decryptField(record.encrypted_readme, projectKey),
    icon: await decryptField(record.encrypted_icon, projectKey),
    color: await decryptField(record.encrypted_color, projectKey),
    pinned: record.pinned === true,
    archived: record.archived === true,
    itemCount: typeof record.item_count === "number" && Number.isFinite(record.item_count) ? Math.max(0, record.item_count) : undefined,
    createdAt: typeof record.created_at === "number" ? record.created_at : null,
    files: [], folders: [], items: [], sources: [], sourceRecords: [],
    projectKey,
    teamId: context.teamId ?? null,
  };
}

export async function loadTuiProjects(client: OpenMatesClient): Promise<TuiProject[]> {
  const context = contextFor(client);
  const records = await client.listProjects({ includeArchived: true, ...context });
  return Promise.all(records.filter((record) => Boolean(record.project_id)).map((record) => projectFromRecord(client, record, context)));
}

function storedPath(metadata: string, displayName: string): string | null {
  let parsed: Record<string, unknown> = {};
  if (metadata) {
    try { parsed = JSON.parse(metadata) as Record<string, unknown>; }
    catch { return null; }
  }
  const candidate = parsed.path ?? parsed.file_path ?? parsed.filename ?? displayName;
  if (typeof candidate !== "string") return null;
  try { return safeFilePath(candidate); }
  catch { return null; }
}

export async function loadTuiProject(client: OpenMatesClient, id: string, chatOnly = false): Promise<TuiProject> {
  const context = contextFor(client);
  const detail = await client.getProject(id, context);
  const project = await projectFromRecord(client, detail.project, context);
  const [itemsResponse, sourceRecords] = await Promise.all([
    client.listProjectItems(id, { ...context, chatOnly }), chatOnly ? Promise.resolve([]) : client.listProjectSources(id, context),
  ]);
  const folderIds = itemsResponse.folders.map((folder) => String(folder.folder_id ?? "")).filter(Boolean);
  const folderByHash = new Map(folderIds.map((folderId) => [createHash("sha256").update(folderId).digest("hex"), folderId]));
  project.folders = await Promise.all(itemsResponse.folders.filter((folder) => typeof folder.folder_id === "string" && folder.folder_id).map(async (folder) => {
    const parentHash = typeof folder.hashed_parent_folder_id === "string" ? folder.hashed_parent_folder_id
      : typeof folder.parent_folder_id === "string" && folderByHash.has(folder.parent_folder_id) ? folder.parent_folder_id : undefined;
    return {
      id: String(folder.folder_id),
      name: await decryptField(folder.encrypted_name, project.projectKey) || "(untitled folder)",
      parentId: parentHash ? folderByHash.get(parentHash) : typeof folder.parent_folder_id === "string" ? folder.parent_folder_id : undefined,
      parentHash,
    };
  }));
  project.files.push(...project.folders.filter((folder) => !folder.parentHash || folder.parentId).map((folder) => ({
    id: folder.id, name: folder.name, path: folder.id, kind: "folder" as const, folderId: folder.parentId,
  })));
  for (const item of itemsResponse.items) {
    const [name, targetId, metadata] = await Promise.all([
      decryptField(item.encrypted_display_name, project.projectKey),
      decryptField(item.target_id_encrypted, project.projectKey),
      decryptField(item.encrypted_metadata, project.projectKey),
    ]);
    const folderHash = typeof item.hashed_folder_id === "string" ? item.hashed_folder_id : undefined;
    const folderId = folderHash ? folderByHash.get(folderHash) ?? `orphan:${folderHash}`
      : typeof item.folder_id === "string" ? item.folder_id : undefined;
    project.items.push({ id: item.project_item_id, type: item.item_type, name: name || item.item_type, targetId, folderId });
    if (item.item_type === "embed") {
      const path = storedPath(metadata, name);
      if (path && targetId) project.files.push({ id: item.project_item_id, name: path.split("/").at(-1) || path, path, kind: "stored", folderId, embedId: targetId });
    }
  }
  project.sourceRecords = sourceRecords;
  project.itemCount ??= project.items.length;
  project.sources = await Promise.all(sourceRecords.map(async (source) => ({
    id: source.source_id,
    name: await decryptField(source.encrypted_display_name, project.projectKey) || source.source_id,
    status: source.status ?? "offline",
    type: source.source_type,
  })));
  // A linked README is client-decrypted, with the same file policy as preview.
  const readme = project.files.find((file) => file.path.toLowerCase() === "readme.md");
  if (!project.readme && readme) {
    try { project.readme = await readTuiProjectFile(client, project, readme); }
    catch { /* A missing or unsupported linked file is still listed. */ }
  }
  return project;
}

function safeRemotePath(path: string): string {
  if (path === ".") return path;
  return safeFilePath(path);
}

/** Explicit remote browsing; callers invoke this only after opening Files. */
export async function loadTuiProjectFiles(
  client: OpenMatesClient,
  project: TuiProject,
  options: { folderId?: string; sourceId?: string; path?: string; query?: string } = {},
): Promise<TuiProjectFile[]> {
  if (!options.sourceId) {
    if (options.path && options.path !== ".") throw new Error("Select a Project source before browsing a remote path.");
    if (options.folderId && !project.folders.some((folder) => folder.id === options.folderId)) throw new Error("Project folder not found.");
    return filteredProjectFiles(project.files.filter((file) => (file.folderId ?? null) === (options.folderId ?? null)), options.query);
  }
  if (options.folderId) throw new Error("Choose a local folder or a remote source.");
  const source = project.sourceRecords.find((item) => item.source_id === options.sourceId);
  if (!source) throw new Error("Project source not found.");
  const path = safeRemotePath(options.path || ".");
  if (project.folders.some((folder) => folder.id === path)) throw new Error("Use the local folder ID without a Project source.");
  const query = options.query?.trim();
  if (query && Buffer.byteLength(query, "utf8") > 256) throw new Error("Search query exceeds 256 bytes.");
  const result = await requestProjectRemoteOperation({
    client, projectId: project.id, projectKey: project.projectKey, source,
    operation: query ? "search" : "list",
    arguments: query ? { query, target: "files", mode: "literal", path } : { path },
    context: contextFor(client, project),
  });
  const record = result && typeof result === "object" ? result as Record<string, unknown> : {};
  const entries = Array.isArray(record.entries) ? record.entries : Array.isArray(record.matches) ? record.matches : [];
  const remoteFiles = entries.flatMap((entry): TuiProjectFile[] => {
    if (!entry || typeof entry !== "object") return [];
    const item = entry as Record<string, unknown>;
    if (typeof item.path !== "string") return [];
    let entryPath: string;
    try { entryPath = safeRemotePath(item.path); } catch { return []; }
    const kind = item.kind === "directory" ? "folder" : "remote";
    return [{ id: `${source.source_id}:${entryPath}`, name: entryPath.split("/").at(-1) || entryPath, path: entryPath, kind, sourceId: source.source_id }];
  });
  return remoteFiles;
}

/** Search only the currently visible namespace, preserving its selection order. */
export function filteredProjectFiles(files: TuiProjectFile[], query = ""): TuiProjectFile[] {
  const needle = query.trim().toLocaleLowerCase();
  return needle ? files.filter((file) => `${file.name} ${file.path}`.toLocaleLowerCase().includes(needle)) : files;
}

export function parentTuiProjectFolderId(project: TuiProject, folderId: string): string | null {
  const folder = project.folders.find((item) => item.id === folderId);
  if (!folder) throw new Error("Project folder not found.");
  return folder.parentId ?? null;
}

export async function readTuiProjectFile(client: OpenMatesClient, project: TuiProject, file: TuiProjectFile): Promise<string> {
  if (file.kind === "folder") throw new Error("Select a file to preview.");
  const path = safeRemotePath(file.path);
  if (file.kind === "stored") {
    if (!file.embedId || !project.files.some((candidate) => candidate.id === file.id && candidate.embedId === file.embedId)) {
      throw new Error("Stored file is not linked to this Project.");
    }
    const head = await client.readEncryptedProjectFile(project.id, file.embedId, project.projectKey, contextFor(client, project));
    const content = head.content.code ?? head.content.content;
    if (typeof content !== "string" || Buffer.byteLength(content, "utf8") > 200 * 1024 || content.includes("\0")) {
      throw new Error("This file has no supported text preview.");
    }
    return content;
  }
  const source = project.sourceRecords.find((candidate) => candidate.source_id === file.sourceId);
  if (!source || source.status !== "connected") throw new Error("Project source is unavailable.");
  const result = await requestProjectRemoteOperation({
    client, projectId: project.id, projectKey: project.projectKey, source,
    operation: "read_text", arguments: { path }, context: contextFor(client, project),
  });
  const content = result && typeof result === "object" ? (result as Record<string, unknown>).content : null;
  if (typeof content !== "string") throw new Error("This file has no text preview.");
  return (result as Record<string, unknown>).truncated === true ? `${content}\n[Preview truncated]` : content;
}

export function filteredProjects(projects: TuiProject[], query = ''): TuiProject[] {
  const term = query.trim().toLocaleLowerCase();
  return projects.filter(project => !term || `${project.name} ${project.slug} ${project.description}`.toLocaleLowerCase().includes(term));
}

function projectCardColor(color: string): string {
  if (/^#[\da-f]{6}$/i.test(color)) return color;
  if (/^#[\da-f]{3}$/i.test(color)) return `#${[...color.slice(1)].map((digit) => digit.repeat(2)).join("")}`;
  return PRIMARY_GRADIENT.start;
}

/** Project summaries in the shared horizontal card viewport. */
export function renderProjectCarousel(projects: TuiProject[], width: number, selectedIndex: number, focused: boolean): TuiLine[] {
  if (!projects.length) return [];
  const selected = Math.max(0, Math.min(projects.length - 1, selectedIndex));
  const cards = projects.map((project) => {
    const count = project.itemCount ?? project.items.length;
    return {
      title: safeText(project.name),
      description: safeText(project.description),
      footer: `${count} ${count === 1 ? "item" : "items"}${project.pinned ? " · Pinned" : ""}${project.archived ? " · Archived" : ""}`,
      background: projectCardColor(project.color),
    };
  });
  return [...renderCardCarousel(cards, width, selected, focused), "",
    centeredCarouselText(`Project ${selected + 1} of ${projects.length} · ←/→ choose project · Enter open`, width)];
}

export function renderProjectList(projects: TuiProject[], options: { width: number; selectedId?: string; query?: string }): string[] {
  const query = options.query?.trim().toLocaleLowerCase() ?? "";
  const matches = filteredProjects(projects, query);
  if (matches.length === 0) return [query ? "No matching Projects." : "No Projects yet. Press n to create one."];
  return matches.flatMap((project) => {
    const count = project.itemCount ?? project.items.length;
    const rows = [
      `[${safeText(project.icon || "folder")}]  ${project.name}${project.pinned ? "  *" : ""}`,
      `${count} ${count === 1 ? "item" : "items"}${project.archived ? "  |  Archived" : ""}`,
      ...(project.description ? [project.description] : []),
    ];
    return [...renderProjectCard(project.id === options.selectedId, rows, options.width, "PROJECT", 88), ""];
  });
}

function renderProjectCard(selected: boolean, rows: string[], width: number, label = "PROJECT", maxCardWidth = width): string[] {
  if (width < 8) return [clip(label, width), ...rows.map((row) => clip(row, width))];
  const cardWidth = Math.max(8, Math.min(Math.floor(width), Math.floor(maxCardWidth)));
  const prefix = selected ? "> " : "  ";
  const innerWidth = cardWidth - prefix.length - 2;
  const heading = clip(label, innerWidth - 3);
  const top = `${prefix}+--${heading}${"-".repeat(Math.max(0, innerWidth - cells(heading) - 2))}+`;
  const body = rows.map((row) => `${prefix}| ${padCells(safeText(row), innerWidth - 2)} |`);
  return [top, ...body, `${prefix}+${"-".repeat(innerWidth)}+`];
}

function startedLabel(createdAt: number | null | undefined): string | null {
  if (!createdAt || !Number.isFinite(createdAt)) return null;
  const date = new Date(createdAt < 10_000_000_000 ? createdAt * 1000 : createdAt);
  return Number.isNaN(date.getTime()) ? null : `Started ${date.toISOString().slice(0, 10)}`;
}

function projectHeroLine(value: string, width: number, bold = false): TuiLine {
  const clean = safeText(value);
  const inset = Math.max(0, Math.floor((width - cells(clean)) / 2));
  return { text: padCells(`${" ".repeat(inset)}${clip(clean, width)}`, width), background: APP_GRADIENTS.weather.start, color: "#ffffff", bold };
}

/** The web header centers the kicker, identity, description and date. */
export function renderProjectIdentity(project: TuiProject, options: { width: number }): TuiLine[] {
  const width = Math.max(1, options.width);
  const count = project.itemCount ?? project.items.length;
  const rows = [
    "Project",
    "",
    `[${safeText(project.icon || "folder")}]  ${project.name}`,
    project.description || "Add chats, embeds, PDFs, sheets, images, audio, video, code, mail, and files.",
    "",
    `${startedLabel(project.createdAt) ?? "Started recently"}  ·  ${count} ${count === 1 ? "item" : "items"}`,
  ];
  return rows.flatMap((row, index) => row
    ? [projectHeroLine(row, width, index === 0 || index === 2)]
    : [projectHeroLine("", width)]);
}

/** A visibly selected tab strip, shared by the Overview, Files and Tasks panes. */
export function renderProjectTabs(tab: "overview" | "files" | "tasks", width: number): string[] {
  const labels = (["overview", "files", "tasks"] as const).map((name, index) =>
    `${name === tab ? "[" : " "}${name[0]!.toUpperCase() + name.slice(1)} · ${index + 1}${name === tab ? "]" : " "}`);
  const text = labels.join("  ");
  const inset = Math.max(0, Math.floor((width - cells(text)) / 2));
  return ["", `${" ".repeat(inset)}${clip(text, width)}`, ""];
}

export function renderProjectDetail(project: TuiProject, options: {
  width: number; tab: "overview" | "files" | "tasks"; files?: TuiProjectFile[];
  selectedFileId?: string; query?: string; folderId?: string; sourceId?: string; path?: string;
}): TuiLine[] {
  const width = options.width;
  const lines: TuiLine[] = [...renderProjectIdentity(project, { width }), ...renderProjectTabs(options.tab, width)];
  if (options.tab === "overview") {
    lines.push(...renderProjectCard(false, project.readme
      ? project.readme.split("\n")
      : ["No project overview created yet."], width, "OVERVIEW"));
    const links = project.items.filter((item) => item.type !== "embed");
    if (links.length) {
      lines.push("", ...renderProjectCard(false, links.map((item) => `${item.type}: ${item.name}`), width, "LINKED WORK"));
    }
    return lines;
  }
  if (options.tab === "tasks") return [...lines, ...renderProjectCard(false, ["Project tasks load in the Tasks pane."], width, "TASKS")];
  const files = options.files ?? project.files.filter((file) => (file.folderId ?? null) === (options.folderId ?? null));
  const folder = options.folderId ? project.folders.find((item) => item.id === options.folderId) : undefined;
  const breadcrumb: string[] = [];
  let ancestor = folder;
  const visited = new Set<string>();
  while (ancestor && !visited.has(ancestor.id)) {
    breadcrumb.unshift(ancestor.name);
    visited.add(ancestor.id);
    ancestor = ancestor.parentId ? project.folders.find((item) => item.id === ancestor?.parentId) : undefined;
  }
  const remoteSource = options.sourceId ? project.sources.find((source) => source.id === options.sourceId) : undefined;
  const location = remoteSource ? [remoteSource.name, ...((options.path && options.path !== ".") ? options.path.split("/") : [])] : breadcrumb;
  lines.push(clip(`  Files / ${location.join(" / ")}`, width));
  const visible = filteredProjectFiles(files, options.query);
  const folderCount = visible.filter((file) => file.kind === "folder").length;
  const fileCount = visible.length - folderCount;
  const summary = `${folderCount} ${folderCount === 1 ? "folder" : "folders"}, ${fileCount} ${fileCount === 1 ? "file" : "files and embeds"}`;
  const rows = [summary, options.query?.trim() ? `Search: ${options.query.trim()}` : "Search files  |  Name A-Z", `${visible.length} ${visible.length === 1 ? "entry" : "entries"}`];
  if (visible.length === 0) rows.push(options.query?.trim() ? "No matching files." : "No files in this location.");
  for (const file of visible) {
    const icon = file.kind === "folder" ? "folder" : file.kind === "stored" ? "embed" : "file";
    const context = file.sourceId ? `  (${project.sources.find((source) => source.id === file.sourceId)?.name || "source"})` : "";
    rows.push(`${file.id === options.selectedFileId ? ">" : " "} [${icon}] ${file.name}${context}`);
  }
  lines.push(...renderProjectCard(false, rows, width, "FILES"));
  return lines;
}

export function buildProjectForm(): TuiForm {
  return {
    kind: "project-create", title: "Create Project", fieldIndex: 0,
    fields: [
      { name: "name", label: "Name", value: "" },
      { name: "description", label: "Description", value: "", multiline: true },
      { name: "write_mode", label: "File changes", value: "always_ask", options: ["always_ask", "apply_and_show"] },
    ],
  };
}

export async function submitProjectForm(client: OpenMatesClient, form: TuiForm, chatOrganizationOnly = false): Promise<TuiProject> {
  const name = formValue(form, "name").trim();
  if (!name) throw new Error("Project name is required.");
  const writeMode = formValue(form, "write_mode");
  if (writeMode !== "always_ask" && writeMode !== "apply_and_show") throw new Error("Choose a file change policy.");
  const context = contextFor(client);
  const wrapping = await client.projectWrappingKey(context);
  const key = randomBytes(32);
  const timestamp = Math.floor(Date.now() / 1000);
  const slug = await buildEncryptedObjectSlugMetadata({ value: name, encryptionKey: key, lookupKey: wrapping.key });
  const focus = { focus_id: randomUUID(), name: `Work on ${name}`, instructions: `Help with work in ${name}. Follow the user's instructions and the Project's connected source guidance.`, source: "generated" };
  const payload: ProjectRecord = {
    project_id: randomUUID(), encrypted_project_key: wrapping.teamId ? null : await encryptBytesWithAesGcm(key, wrapping.key),
    encrypted_slug: slug.encrypted_slug, slug_lookup_hash: slug.slug_lookup_hash,
    encrypted_name: await encryptWithAesGcmCombined(name, key),
    encrypted_description: await encryptWithAesGcmCombined(formValue(form, "description"), key),
    encrypted_icon: await encryptWithAesGcmCombined("folder", key),
    encrypted_color: await encryptWithAesGcmCombined("default", key),
    pinned: false, created_at: timestamp, updated_at: timestamp, last_opened_at: timestamp,
    write_mode: chatOrganizationOnly ? null : writeMode, default_focus_id: focus.focus_id,
    encrypted_settings: await encryptWithAesGcmCombined(JSON.stringify({ default_focus: focus }), key),
    key_wrappers: wrapping.teamId ? [{
      key_type: "team", hashed_team_id: createHash("sha256").update(wrapping.teamId).digest("hex"),
      team_key_epoch: 1, encrypted_project_key: await encryptBytesWithAesGcm(key, wrapping.key),
      wrapper_version: 1, created_at: timestamp,
    }] : [],
  };
  const result = await client.createProject({ ...payload, ...(chatOrganizationOnly ? { chat_organization_only: true } : {}) }, context);
  return projectFromRecord(client, { ...payload, ...((result.project ?? {}) as ProjectRecord) }, context);
}
