// Loads the root README.md shown on a Project's Overview tab.
// Stored files use the existing project-key decryption path, including legacy Markdown uploads.
// Connected sources use the bounded encrypted remote read protocol.
// Public image URLs are proxied, while project-relative images resolve only through encrypted items.
// The service returns renderer-ready content without granting raw HTML or network access.

import { proxyImage, MAX_WIDTH_CONTENT_IMAGE } from "../utils/imageProxy";
import { fetchAndDecryptImage } from "../components/embeds/images/imageEmbedCrypto";
import {
  readEncryptedProjectFile,
  requestProjectRemoteAccess,
  type ProjectItemViewModel,
  type ProjectRemoteAccessContext,
  type ProjectRemoteDirectoryResult,
  type ProjectRemoteTextResult,
  type ProjectSourceViewModel,
  type ProjectViewModel,
} from "./projectService";

export interface ProjectReadmeDocument {
  content: string;
  path: "README.md";
  origin: "stored" | "connected";
  sourceId?: string;
  truncated?: boolean;
  /** Markdown source URL to a browser-safe proxy, data URL, or decrypted blob URL. */
  imageUrls: Record<string, string>;
}

export type ProjectReadmeState =
  | { status: "loading" }
  | { status: "ready"; document: ProjectReadmeDocument }
  | { status: "empty" }
  | { status: "error"; message: string };

interface LoadProjectReadmeInput {
  project: ProjectViewModel;
  items: readonly ProjectItemViewModel[];
  sources: readonly ProjectSourceViewModel[];
  remoteContext: ProjectRemoteAccessContext;
  signal?: AbortSignal;
}

const README_PATH = "README.md" as const;
const CONTENT_FIELDS = ["code", "content", "markdown", "text"] as const;

function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

function storedReadmePath(item: ProjectItemViewModel): string | null {
  const metadataPath = typeof item.metadata.path === "string" ? item.metadata.path : "";
  const remotePath = typeof item.metadata.remote_path === "string" ? item.metadata.remote_path : "";
  const candidate = metadataPath || remotePath || item.displayName;
  if (!candidate || candidate.startsWith("/") || candidate.includes("\\")) return null;
  if (candidate.includes("/")) return null;
  return basename(candidate).toLowerCase() === README_PATH.toLowerCase() ? README_PATH : null;
}

export function findStoredProjectReadme(items: readonly ProjectItemViewModel[]): ProjectItemViewModel | null {
  const readmes = items.filter((item) =>
    item.item_type === "embed" && !item.encrypted.hashed_folder_id && storedReadmePath(item),
  );
  return readmes.sort((a, b) =>
    readmeUploadTime(b) - readmeUploadTime(a) ||
    b.encrypted.updated_at - a.encrypted.updated_at ||
    b.encrypted.created_at - a.encrypted.created_at,
  )[0] ?? null;
}

function readmeUploadTime(item: ProjectItemViewModel): number {
  const value = item.metadata.readme_uploaded_at_ms;
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : 0;
}

export function projectReadmeText(content: Record<string, unknown>): string | null {
  for (const field of CONTENT_FIELDS) {
    const value = content[field];
    if (typeof value === "string") return value;
  }
  return null;
}

/** Only public HTTP(S) images are rendered. Private and relative paths stay text-only. */
export function safeProjectReadmeImageUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return proxyImage(url.href, MAX_WIDTH_CONTENT_IMAGE);
  } catch {
    return null;
  }
}

function projectItemPath(item: ProjectItemViewModel): string | null {
  const raw = typeof item.metadata.path === "string"
    ? item.metadata.path
    : typeof item.metadata.remote_path === "string" ? item.metadata.remote_path : item.displayName;
  if (!raw || raw.startsWith("/") || raw.includes("\\")) return null;
  const parts = raw.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return null;
  return parts.join("/");
}

function relativeImagePath(value: string): string | null {
  if (!value || value.startsWith("/") || value.startsWith("\\") || value.startsWith("#")) return null;
  const withoutSuffix = value.split(/[?#]/, 1)[0];
  let decoded: string;
  try {
    decoded = decodeURIComponent(withoutSuffix).replace(/^\.\//, "");
  } catch {
    return null;
  }
  if (!decoded || decoded.includes("\\")) return null;
  const parts: string[] = [];
  for (const part of decoded.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.pop()) return null;
      continue;
    }
    parts.push(part);
  }
  return parts.length ? parts.join("/") : null;
}

export function projectReadmeImageSources(markdown: string): string[] {
  const sources = new Set<string>();
  const pattern = /!\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(markdown)) !== null) {
    const source = (match[1] || match[2] || "").trim();
    if (source) sources.add(source);
  }

  const normalizeLabel = (label: string): string => label.trim().replace(/\s+/g, " ").toLowerCase();
  const definitions = new Map<string, string>();
  const definitionPattern = /^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|([^\s]+))(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*$/gm;
  while ((match = definitionPattern.exec(markdown)) !== null) {
    const source = (match[2] || match[3] || "").trim();
    if (source) definitions.set(normalizeLabel(match[1]), source);
  }
  const referencePattern = /!\[([^\]]+)\]\s*\[([^\]]*)\]/g;
  while ((match = referencePattern.exec(markdown)) !== null) {
    const label = normalizeLabel(match[2] || match[1]);
    const source = definitions.get(label);
    if (source) sources.add(source);
  }
  return Array.from(sources);
}

function imageVariant(content: Record<string, unknown>): Record<string, unknown> | null {
  const files = content.files;
  if (!files || typeof files !== "object" || Array.isArray(files)) return null;
  const record = files as Record<string, unknown>;
  for (const name of ["preview", "full", "original"]) {
    const value = record[name];
    if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  }
  return null;
}

async function internalImageUrl(content: Record<string, unknown>): Promise<string | null> {
  const dataUrl = content.data_url;
  if (typeof dataUrl === "string" && /^data:image\/(?:png|jpeg|gif|webp|avif);base64,/i.test(dataUrl)) return dataUrl;
  const variant = imageVariant(content);
  const s3Key = variant?.s3_key;
  const aesKey = content.aes_key;
  if (typeof s3Key !== "string" || typeof aesKey !== "string") return null;
  const nonce = typeof variant?.aes_nonce === "string"
    ? variant.aes_nonce
    : typeof content.aes_nonce === "string" ? content.aes_nonce : "";
  const blob = await fetchAndDecryptImage(
    typeof content.s3_base_url === "string" ? content.s3_base_url : "",
    s3Key,
    aesKey,
    nonce,
    variant,
  );
  return URL.createObjectURL(blob);
}

async function resolveReadmeImages(
  markdown: string,
  project: ProjectViewModel,
  items: readonly ProjectItemViewModel[],
  teamId?: string | null,
): Promise<Record<string, string>> {
  const urls: Record<string, string> = {};
  for (const source of projectReadmeImageSources(markdown)) {
    const external = safeProjectReadmeImageUrl(source);
    if (external) {
      urls[source] = external;
      continue;
    }
    const path = relativeImagePath(source);
    if (!path) continue;
    const item = items.find((candidate) =>
      candidate.item_type === "embed" && !candidate.encrypted.hashed_folder_id && projectItemPath(candidate) === path,
    );
    if (!item) continue;
    try {
      const head = await readEncryptedProjectFile(project, item.target_id, { teamId });
      const url = await internalImageUrl(head.content);
      if (url) urls[source] = url;
    } catch {
      // Missing keys or unsupported legacy media remain a visible text placeholder.
    }
  }
  return urls;
}

export function releaseProjectReadmeImages(document: ProjectReadmeDocument): void {
  for (const url of Object.values(document.imageUrls)) {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url);
  }
}

export async function loadProjectReadme(input: LoadProjectReadmeInput): Promise<ProjectReadmeState> {
  const stored = findStoredProjectReadme(input.items);
  if (stored) {
    try {
      const head = await readEncryptedProjectFile(input.project, stored.target_id, {
        teamId: input.remoteContext.teamId,
      });
      const content = projectReadmeText(head.content);
      if (content !== null) {
        const imageUrls = await resolveReadmeImages(content, input.project, input.items, input.remoteContext.teamId);
        return { status: "ready", document: { content, path: README_PATH, origin: "stored", imageUrls } };
      }
      return { status: "error", message: "This README could not be displayed." };
    } catch {
      return { status: "error", message: "This README could not be opened." };
    }
  }

  const readCapableSources = input.sources.filter((source) => source.capabilities.includes("read"));
  const readableSources = readCapableSources.filter((source) => source.status === "connected");
  let couldNotCheckSource = readCapableSources.length !== readableSources.length;
  for (const source of readableSources) {
    try {
      const directory = await requestProjectRemoteAccess<ProjectRemoteDirectoryResult>(
        input.project,
        source,
        input.remoteContext,
        "list",
        { path: "." },
        input.signal,
      );
      const readme = directory.entries.find((entry) =>
        entry.kind === "file" && entry.path.replace(/^\.\//, "").toLowerCase() === README_PATH.toLowerCase(),
      );
      if (!readme) {
        if (directory.omitted > 0) couldNotCheckSource = true;
        continue;
      }
      const result = await requestProjectRemoteAccess<ProjectRemoteTextResult>(
        input.project,
        source,
        input.remoteContext,
        "read_text",
        { path: readme.path },
        input.signal,
      );
      const imageUrls = await resolveReadmeImages(result.content, input.project, input.items, input.remoteContext.teamId);
      return {
        status: "ready",
        document: {
          content: result.content,
          path: README_PATH,
          origin: "connected",
          sourceId: source.source_id,
          truncated: result.truncated,
          imageUrls,
        },
      };
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      // A failed source check cannot prove that its root README is absent.
      couldNotCheckSource = true;
    }
  }
  return couldNotCheckSource
    ? { status: "error", message: "Could not check every Project source for a README." }
    : { status: "empty" };
}
