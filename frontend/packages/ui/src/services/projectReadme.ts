// Loads the root README.md shown on a Project's Overview tab.
// Stored files use the existing project-key decryption path, including legacy Markdown uploads.
// Connected sources use the bounded encrypted remote read protocol.
// Public image URLs are proxied; relative images use encrypted Project items or
// bounded encrypted reads from the connected source.
// The service returns renderer-ready content without granting raw HTML or network access.

import { proxyImage, MAX_WIDTH_CONTENT_IMAGE } from "../utils/imageProxy";
import { fetchAndDecryptImage } from "../components/embeds/images/imageEmbedCrypto";
import {
  readEncryptedProjectFile,
  requestProjectRemoteAccess,
  type ProjectItemViewModel,
  type ProjectRemoteAccessContext,
  type ProjectRemoteDirectoryResult,
  type ProjectRemoteImageChunkResult,
  type ProjectRemoteTextResult,
  type ProjectSourceViewModel,
  type ProjectViewModel,
} from "./projectService";
import { PROJECT_RUST_CORE, decideProject, projectRule } from "./projectState/decide";
import {
  projectReadmeFind,
  projectReadmeText as projectReadmeTextRule,
  readmeImageSources,
  readmePublicImageHref,
  type ReadmeItem,
} from "./projectState/projectReadmePolicy";

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
// Read stride of connected-source image chunks (the chunk check enforces each length).
const REMOTE_IMAGE_CHUNK_BYTES = 128 * 1024;

/** The item fields the README rules read (keeps the Rust input small). */
function readmeItems(items: readonly ProjectItemViewModel[]): ReadmeItem[] {
  return items.map((item) => ({
    item_type: item.item_type,
    displayName: item.displayName,
    metadata: {
      path: item.metadata.path, remote_path: item.metadata.remote_path, readme_uploaded_at_ms: item.metadata.readme_uploaded_at_ms,
    },
    encrypted: {
      hashed_folder_id: item.encrypted.hashed_folder_id, updated_at: item.encrypted.updated_at, created_at: item.encrypted.created_at,
    },
  }));
}

export function findStoredProjectReadme(items: readonly ProjectItemViewModel[]): ProjectItemViewModel | null {
  const { index } = projectReadmeFind({ items: readmeItems(items) });
  return index === null ? null : items[index];
}

async function findStoredReadmeRust(items: readonly ProjectItemViewModel[]): Promise<ProjectItemViewModel | null> {
  const { index } = await decideProject("projectReadmeFind", { items: readmeItems(items) });
  return index === null ? null : items[index];
}

export function projectReadmeText(content: Record<string, unknown>): string | null {
  return projectReadmeTextRule({ content }).text;
}

/**
 * External images always pass through the privacy-preserving image proxy. Stays
 * synchronous TypeScript: ProjectReadme.svelte calls it while rendering.
 */
export function safeProjectReadmeImageUrl(value: string): string | null {
  const href = readmePublicImageHref(value);
  return href === null ? null : proxyImage(href, MAX_WIDTH_CONTENT_IMAGE);
}

export function projectReadmeImageSources(markdown: string): string[] {
  return readmeImageSources(markdown);
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
  remote?: { source: ProjectSourceViewModel; context: ProjectRemoteAccessContext; signal?: AbortSignal },
): Promise<Record<string, string>> {
  const urls: Record<string, string> = {};
  // The rules decide every image up front (pure); the reads below keep their order.
  const planInput = { markdown, items: readmeItems(items), remote: Boolean(remote) };
  const { images } = PROJECT_RUST_CORE
    ? await decideProject("projectReadmeImages", planInput) : projectRule("projectReadmeImages", planInput);
  try {
    for (const image of images) {
      const source = image.source;
      if (image.kind === "external") {
        urls[source] = proxyImage(image.href, MAX_WIDTH_CONTENT_IMAGE);
        continue;
      }
      if (image.kind === "remote") {
        if (!remote) continue;
        try {
          const url = await readConnectedProjectImage(project, remote.source, remote.context, image.path, remote.signal);
          if (url) urls[source] = url;
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") throw error;
          // Protected, ignored, oversized, changed, and unsupported source files stay placeholders.
        }
        continue;
      }
      const item = items[image.index];
      if (item) {
        try {
          const head = await readEncryptedProjectFile(project, item.target_id, { teamId });
          const url = await internalImageUrl(head.content);
          if (url) urls[source] = url;
        } catch {
          // Missing keys or unsupported legacy media remain a visible text placeholder.
        }
      }
    }
    return urls;
  } catch (error) {
    for (const url of Object.values(urls)) {
      if (url.startsWith("blob:")) URL.revokeObjectURL(url);
    }
    throw error;
  }
}

export async function readConnectedProjectImage(
  project: ProjectViewModel,
  source: ProjectSourceViewModel,
  context: ProjectRemoteAccessContext,
  path: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const chunks: Uint8Array[] = [];
  let size = 0;
  let mime = "";
  let hash = "";
  for (let offset = 0; offset === 0 || offset < size; offset += REMOTE_IMAGE_CHUNK_BYTES) {
    const result = await requestProjectRemoteAccess<ProjectRemoteImageChunkResult>(
      project, source, context, "read_image_chunk", { path, offset }, signal,
    );
    const checkInput = {
      offset, size, mime, hash,
      result: { offset: result.offset, size_bytes: result.size_bytes, mime_type: result.mime_type, content_hash: result.content_hash },
    };
    const check = PROJECT_RUST_CORE
      ? await decideProject("projectImageChunkCheck", checkInput) : projectRule("projectImageChunkCheck", checkInput);
    if (!check.ok) return null;
    size = result.size_bytes;
    mime = result.mime_type;
    hash = result.content_hash;
    const binary = atob(result.content_base64);
    const chunk = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    if (chunk.length !== check.expectedLength) return null;
    chunks.push(chunk);
  }
  const bytes = new Uint8Array(size);
  let written = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, written);
    written += chunk.length;
  }
  if (written !== size) return null;
  return URL.createObjectURL(new Blob([bytes.buffer], { type: mime }));
}

export function releaseProjectReadmeImages(document: ProjectReadmeDocument): void {
  for (const url of Object.values(document.imageUrls)) {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url);
  }
}

export async function loadProjectReadme(input: LoadProjectReadmeInput): Promise<ProjectReadmeState> {
  const stored = PROJECT_RUST_CORE ? await findStoredReadmeRust(input.items) : findStoredProjectReadme(input.items);
  if (stored) {
    try {
      const head = await readEncryptedProjectFile(input.project, stored.target_id, {
        teamId: input.remoteContext.teamId,
      });
      const content = PROJECT_RUST_CORE
        ? (await decideProject("projectReadmeText", { content: head.content })).text
        : projectReadmeText(head.content);
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
      const pickInput = {
        entries: directory.entries.map((entry) => ({ path: entry.path, kind: entry.kind })), omitted: directory.omitted,
      };
      const readme = PROJECT_RUST_CORE
        ? await decideProject("projectReadmeRemotePick", pickInput) : projectRule("projectReadmeRemotePick", pickInput);
      if (readme.path === null) {
        if (readme.incomplete) couldNotCheckSource = true;
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
      const imageUrls = await resolveReadmeImages(result.content, input.project, input.items, input.remoteContext.teamId, {
        source, context: input.remoteContext, signal: input.signal,
      });
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
