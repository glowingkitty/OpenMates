// frontend/packages/ui/src/services/projectState/projectReadmePolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// README decisions of projectReadme.ts: which stored item is the root README, its
// text field, how each Markdown image source resolves (public URL, connected-source
// path, stored Project item), the connected-source README entry and the image chunk
// checks. Fetch, remote reads, image decryption, blob URLs and the image proxy stay
// in projectReadme.ts; with VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides
// (web_projects/readme.rs). No imports (generate.mjs loads this file in Node).

const README_PATH = "README.md";
const CONTENT_FIELDS = ["code", "content", "markdown", "text"] as const;
const REMOTE_IMAGE_CHUNK_BYTES = 128 * 1024;
const MAX_REMOTE_IMAGE_BYTES = 2 * 1024 * 1024;
const MAX_REMOTE_README_IMAGES = 8;

/** The fields of a Project item view model these rules read. */
export interface ReadmeItem {
  item_type: string;
  displayName: string;
  metadata: Record<string, unknown>;
  encrypted: { hashed_folder_id?: string | null; updated_at: number; created_at: number };
}

function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

function storedReadmePath(item: ReadmeItem): string | null {
  const metadataPath = typeof item.metadata.path === "string" ? item.metadata.path : "";
  const remotePath = typeof item.metadata.remote_path === "string" ? item.metadata.remote_path : "";
  const candidate = metadataPath || remotePath || item.displayName;
  if (!candidate || candidate.startsWith("/") || candidate.includes("\\")) return null;
  if (candidate.includes("/")) return null;
  return basename(candidate).toLowerCase() === README_PATH.toLowerCase() ? README_PATH : null;
}

function readmeUploadTime(item: ReadmeItem): number {
  const value = item.metadata.readme_uploaded_at_ms;
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : 0;
}

/** Index of the newest root README item (latest README upload, then update, then creation), or null. */
export function projectReadmeFind(input: { items: readonly ReadmeItem[] }): { index: number | null } {
  const readmes = input.items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.item_type === "embed" && !item.encrypted.hashed_folder_id && storedReadmePath(item));
  const best = readmes.sort((a, b) =>
    readmeUploadTime(b.item) - readmeUploadTime(a.item) ||
    b.item.encrypted.updated_at - a.item.encrypted.updated_at ||
    b.item.encrypted.created_at - a.item.encrypted.created_at,
  )[0];
  return { index: best ? best.index : null };
}

/** The first string content field of a decrypted README head. */
export function projectReadmeText(input: { content: Record<string, unknown> }): { text: string | null } {
  for (const field of CONTENT_FIELDS) {
    const value = input.content[field];
    if (typeof value === "string") return { text: value };
  }
  return { text: null };
}

/** Normalized href of a public http(s) image URL that may go through the image proxy, else null. */
export function readmePublicImageHref(value: string): string | null {
  try {
    const url = new URL(value.startsWith("//") ? `https:${value}` : value);
    if ((url.protocol !== "https:" && url.protocol !== "http:") || url.username || url.password) return null;
    const hostname = url.hostname.toLowerCase();
    if (hostname === "localhost" || hostname.endsWith(".localhost")
      || hostname.startsWith("[") || /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname)) return null;
    return url.href;
  } catch {
    return null;
  }
}

function projectItemPath(item: ReadmeItem): string | null {
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

/** Distinct image sources of inline and reference-style Markdown images, in first-seen order. */
export function readmeImageSources(markdown: string): string[] {
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

export type ReadmeImagePlan =
  | { source: string; kind: "external"; href: string }
  | { source: string; kind: "remote"; path: string }
  | { source: string; kind: "item"; path: string; index: number };

/**
 * How each README image resolves: public URLs go through the proxy, relative paths
 * read the connected source (at most 8, `remote`) or the matching stored root item.
 * Sources that resolve to nothing are left out and stay text placeholders.
 */
export function projectReadmeImages(input: { markdown: string; items: readonly ReadmeItem[]; remote: boolean }): { images: ReadmeImagePlan[] } {
  const images: ReadmeImagePlan[] = [];
  let remoteImages = 0;
  for (const source of readmeImageSources(input.markdown)) {
    const href = readmePublicImageHref(source);
    if (href) {
      images.push({ source, kind: "external", href });
      continue;
    }
    const path = relativeImagePath(source);
    if (!path) continue;
    if (input.remote) {
      if (remoteImages >= MAX_REMOTE_README_IMAGES) continue;
      remoteImages += 1;
      images.push({ source, kind: "remote", path });
      continue;
    }
    const index = input.items.findIndex((candidate) =>
      candidate.item_type === "embed" && !candidate.encrypted.hashed_folder_id && projectItemPath(candidate) === path,
    );
    if (index >= 0) images.push({ source, kind: "item", path, index });
  }
  return { images };
}

/** The root README entry of a connected-source listing; `incomplete` when omitted entries hide it. */
export function projectReadmeRemotePick(input: {
  entries: Array<{ path: string; kind: string }>; omitted: number;
}): { path: string | null; incomplete: boolean } {
  const readme = input.entries.find((entry) =>
    entry.kind === "file" && entry.path.replace(/^\.\//, "").toLowerCase() === README_PATH.toLowerCase(),
  );
  return readme ? { path: readme.path, incomplete: false } : { path: null, incomplete: input.omitted > 0 };
}

/** Whether one image chunk continues the read, and the decoded byte length it must have. */
export function projectImageChunkCheck(input: {
  offset: number; size: number; mime: string; hash: string;
  result: { offset: number; size_bytes: number; mime_type: string; content_hash: string };
}): { ok: boolean; expectedLength: number } {
  const { offset, result } = input;
  const ok = !(result.offset !== offset || result.size_bytes <= 0 || result.size_bytes > MAX_REMOTE_IMAGE_BYTES
    || (offset > 0 && (result.size_bytes !== input.size || result.mime_type !== input.mime || result.content_hash !== input.hash)));
  return { ok, expectedLength: ok ? Math.min(REMOTE_IMAGE_CHUNK_BYTES, result.size_bytes - offset) : 0 };
}

export const README_OPS = {
  projectReadmeFind, projectReadmeText, projectReadmeImages, projectReadmeRemotePick, projectImageChunkCheck,
};
