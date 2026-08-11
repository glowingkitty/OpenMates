/**
 * Static example-chat file resolver.
 *
 * Example chats keep public embed metadata in the frontend bundle rather than in
 * IndexedDB. This helper turns those embeds into the same lightweight file rows
 * used by chat settings and the CLI, without touching private user storage.
 */

import type { ExampleChatEmbed, ExampleChatMessage } from "./types";

export interface ChatFileReference {
  embedId: string;
  contentRef: string;
  title: string;
  subtitle: string;
  type: string;
  nodeType: string;
  iconName: string;
  createdAt: number;
  updatedAt: number;
  metadata: string;
  appId: string | null;
  skillId: string | null;
  url: string | null;
  mimeType: string | null;
}

export interface ResolvableChatEmbed {
  embed_id?: string | null;
  embedId?: string | null;
  id?: string | null;
  type?: string | null;
  content?: string | Record<string, unknown> | null;
  parent_embed_id?: string | null;
  embed_ids?: string[] | string | null;
  app_id?: string | null;
  skill_id?: string | null;
  appId?: string | null;
  skillId?: string | null;
  created_at?: number | null;
  createdAt?: number | null;
}

const FILE_LIKE_TYPES = new Set([
  "audio",
  "audio-recording",
  "code",
  "code-code",
  "design",
  "diagram",
  "docs",
  "docs-doc",
  "document",
  "image",
  "images-image",
  "mind-map",
  "mind_map",
  "model3d",
  "music",
  "notebook",
  "pcb_schematic",
  "pdf",
  "recording",
  "remotion-video",
  "sheet",
  "sheets",
  "sheets-sheet",
  "spreadsheet",
  "svg",
  "video",
]);

const URL_FIELDS = [
  "downloadUrl",
  "download_url",
  "file_url",
  "previewAudioUrl",
  "preview_audio_url",
  "previewImageUrl",
  "preview_image_url",
  "previewVideoUrl",
  "preview_video_url",
  "src",
  "url",
  "video_url",
];

const AUDIO_URL_FIELDS = [
  "downloadUrl",
  "download_url",
  "file_url",
  "previewAudioUrl",
  "preview_audio_url",
  "src",
  "url",
];

const VIDEO_URL_FIELDS = [
  "downloadUrl",
  "download_url",
  "file_url",
  "previewVideoUrl",
  "preview_video_url",
  "video_url",
  "src",
  "url",
  "previewImageUrl",
  "preview_image_url",
];

const IMAGE_URL_FIELDS = [
  "downloadUrl",
  "download_url",
  "file_url",
  "previewImageUrl",
  "preview_image_url",
  "src",
  "url",
];

const FILENAME_FIELDS = [
  "filename",
  "file_name",
  "file_path",
  "original_filename",
];

const MIME_EXTENSION: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "audio/mpeg": "mp3",
  "audio/wav": "wav",
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/svg+xml": "svg",
  "image/webp": "webp",
  "model/gltf-binary": "glb",
  "text/html": "html",
  "text/markdown": "md",
  "text/plain": "txt",
  "video/mp4": "mp4",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeEmbedId(embedId: string): string {
  return embedId.startsWith("embed:") ? embedId.slice("embed:".length) : embedId;
}

function cleanString(value: unknown): string {
  if (typeof value !== "string") return "";
  const trimmed = stripQuotes(value.trim());
  if (!trimmed || trimmed === "null" || trimmed === "undefined") return "";
  return trimmed;
}

function stripQuotes(value: string): string {
  const first = value[0];
  if ((first === '"' || first === "'") && value.endsWith(first)) {
    return value.slice(1, -1).replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\'/g, "'");
  }
  return value;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseFlatToonFields(content: string): Record<string, unknown> {
  const fields: Record<string, unknown> = {};
  for (const line of content.split("\n")) {
    if (!line || /^\s/.test(line)) continue;
    const separatorIndex = line.indexOf(":");
    if (separatorIndex <= 0) continue;
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    if (!key || value === "") continue;
    fields[key] = stripQuotes(value);
  }
  return fields;
}

function decodeEmbedContent(content: ResolvableChatEmbed["content"]): Record<string, unknown> {
  if (isRecord(content)) return { ...content };
  if (typeof content !== "string" || !content.trim()) return {};
  const trimmed = content.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      return isRecord(parsed) ? parsed : {};
    } catch {
      return parseFlatToonFields(content);
    }
  }
  return parseFlatToonFields(content);
}

function stringField(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = cleanString(record[key]);
    if (value) return value;
  }
  return "";
}

function basenameFromUrl(url: string): string {
  if (url.startsWith("data:")) return "";
  const withoutQuery = url.split(/[?#]/)[0] || "";
  return withoutQuery.split("/").pop()?.replace(/[^a-zA-Z0-9._-]/g, "_") ?? "";
}

function extensionFromUrl(url: string): string {
  const basename = basenameFromUrl(url);
  const dotIndex = basename.lastIndexOf(".");
  return dotIndex > 0 ? basename.slice(dotIndex + 1).toLowerCase() : "";
}

function extensionFromLanguage(language: string): string {
  const normalized = language.toLowerCase();
  const map: Record<string, string> = {
    bash: "sh",
    css: "css",
    dockerfile: "Dockerfile",
    html: "html",
    javascript: "js",
    json: "json",
    markdown: "md",
    python: "py",
    rust: "rs",
    svelte: "svelte",
    text: "txt",
    typescript: "ts",
    yaml: "yml",
  };
  return (map[normalized] ?? normalized.replace(/[^a-z0-9]/g, "")) || "txt";
}

function nestedFormatFromToon(content: ResolvableChatEmbed["content"]): string {
  if (typeof content !== "string") return "";
  const match = content.match(/\n\s+format:\s*([^\n]+)/);
  return cleanString(match?.[1]);
}

function urlForType(type: string, record: Record<string, unknown>): string {
  if (type.includes("video") || type === "remotion-video") return stringField(record, VIDEO_URL_FIELDS);
  if (type.includes("audio") || type === "music" || type === "recording") return stringField(record, AUDIO_URL_FIELDS);
  if (type.includes("image") || type === "svg") return stringField(record, IMAGE_URL_FIELDS);
  return stringField(record, URL_FIELDS);
}

function inferFallbackExtension(
  type: string,
  record: Record<string, unknown>,
  content: ResolvableChatEmbed["content"],
): string {
  const mimeType = stringField(record, ["mime_type", "file_type", "mimeType"]);
  if (mimeType && MIME_EXTENSION[mimeType]) return MIME_EXTENSION[mimeType];
  const urlExtension = extensionFromUrl(urlForType(type, record));
  if (urlExtension) return urlExtension;
  const nestedFormat = nestedFormatFromToon(content);
  if (nestedFormat) return nestedFormat;
  if (type.includes("video")) return "mp4";
  if (type.includes("audio") || type === "music" || type === "recording") return "mp3";
  if (type.includes("image")) return "png";
  if (type.includes("pdf")) return "pdf";
  if (type.includes("doc") || type === "document") return "docx";
  if (type.includes("sheet") || type === "spreadsheet") return "xlsx";
  if (type === "model3d") return "glb";
  if (type.includes("code") || type === "notebook" || type === "pcb_schematic") {
    return extensionFromLanguage(stringField(record, ["language"]));
  }
  return "txt";
}

function inferTitle(
  embedId: string,
  type: string,
  record: Record<string, unknown>,
  content: ResolvableChatEmbed["content"],
): string {
  const url = urlForType(type, record);
  const urlBasename = basenameFromUrl(url);
  const filename = stringField(record, FILENAME_FIELDS);
  if ((type.includes("video") || type === "music" || type === "audio") && urlBasename) {
    return urlBasename;
  }
  if (filename) return filename.replace(/[/\\]/g, "_");
  if (urlBasename) return urlBasename;
  const title = stringField(record, ["title"]);
  if (title) {
    const extension = inferFallbackExtension(type, record, content);
    return `${title.replace(/[^a-zA-Z0-9._ -]/g, "_").trim()}.${extension}`;
  }
  const extension = inferFallbackExtension(type, record, content);
  return `${type || "file"}-${embedId.slice(0, 8)}.${extension}`;
}

function inferNodeType(title: string, type: string): string {
  const lowerTitle = title.toLowerCase();
  if (type.includes("pdf") || lowerTitle.endsWith(".pdf")) return "pdf";
  if (type.includes("image") || /\.(png|jpe?g|gif|webp|svg|avif|heic|heif)$/.test(lowerTitle)) return "image";
  if (type.includes("video") || /\.(mp4|mov|webm|m4v)$/.test(lowerTitle)) return "video";
  if (type.includes("audio") || type === "music" || type === "recording" || /\.(mp3|wav|m4a|ogg|webm)$/.test(lowerTitle)) return "recording";
  if (type.includes("sheet") || type === "spreadsheet" || /\.(csv|xlsx?|ods)$/.test(lowerTitle)) return "sheets-sheet";
  if (type.includes("doc") || type === "document" || /\.(docx?|odt|rtf)$/.test(lowerTitle)) return "docs-doc";
  if (type === "model3d" || /\.(glb|gltf|obj|stl)$/.test(lowerTitle)) return "model3d";
  if (type.includes("code") || type === "notebook" || type === "pcb_schematic") return "code-code";
  return "file";
}

function iconNameForNodeType(nodeType: string): string {
  if (nodeType === "pdf") return "pdf";
  if (nodeType === "image") return "image";
  if (nodeType === "video") return "video";
  if (nodeType === "recording") return "audio";
  if (nodeType === "sheets-sheet") return "sheets";
  if (nodeType === "docs-doc") return "document";
  if (nodeType === "code-code") return "coding";
  if (nodeType === "model3d") return "3dmodels";
  return "files";
}

function labelForNodeType(nodeType: string, type: string): string {
  if (nodeType === "pdf") return "PDF";
  if (nodeType === "image") return "Image";
  if (nodeType === "video") return "Video";
  if (nodeType === "recording") return type === "music" ? "Music" : "Audio";
  if (nodeType === "sheets-sheet") return "Sheet";
  if (nodeType === "docs-doc") return "Document";
  if (nodeType === "code-code") return type === "notebook" ? "Notebook" : "Code file";
  if (nodeType === "model3d") return "3D model";
  return "File";
}

function formatBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function plural(value: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${value} ${value === 1 ? singular : pluralLabel}`;
}

function buildMetadata(nodeType: string, type: string, record: Record<string, unknown>): string {
  const parts = [labelForNodeType(nodeType, type)];
  const lineCount = numberValue(record.line_count ?? record.lineCount);
  const pageCount = numberValue(record.page_count ?? record.pageCount);
  const wordCount = numberValue(record.word_count ?? record.wordCount);
  const duration = numberValue(record.duration_seconds ?? record.durationSeconds);
  const size = numberValue(record.byte_length ?? record.size_bytes ?? record.sizeBytes);
  if (lineCount) parts.push(plural(lineCount, "line"));
  if (pageCount) parts.push(plural(pageCount, "page"));
  if (wordCount) parts.push(plural(wordCount, "word"));
  if (duration) parts.push(`${duration.toFixed(duration < 10 ? 1 : 0)}s`);
  const sizeLabel = formatBytes(size);
  if (sizeLabel) parts.push(sizeLabel);
  return parts.join(" | ");
}

function isSupportedPublicUrl(url: string): boolean {
  return url.startsWith("/") || url.startsWith("data:") || /^https?:\/\//i.test(url);
}

export function extractEmbedIdsFromContent(content: ResolvableChatEmbed["content"]): string[] {
  const decoded = decodeEmbedContent(content);
  const rawIds = decoded.embed_ids ?? decoded.embedIds;
  const ids = typeof rawIds === "string" ? rawIds.split(/[|,]/) : rawIds;
  if (!Array.isArray(ids)) return [];
  return ids
    .map((id) => cleanString(id))
    .filter(Boolean)
    .map(normalizeEmbedId);
}

function buildEmbedLookup(embeds: ExampleChatEmbed[]): Map<string, ExampleChatEmbed> {
  const lookup = new Map<string, ExampleChatEmbed>();
  for (const embed of embeds) {
    if (!embed.embed_id) continue;
    lookup.set(normalizeEmbedId(embed.embed_id), embed);
  }
  return lookup;
}

function buildEmbedRefLookup(embeds: ExampleChatEmbed[]): Map<string, string> {
  const lookup = new Map<string, string>();
  for (const embed of embeds) {
    const embedId = normalizeEmbedId(embed.embed_id);
    lookup.set(embedId, embedId);
    lookup.set(`embed:${embedId}`, embedId);
    const decoded = decodeEmbedContent(embed.content);
    const embedRef = stringField(decoded, ["embed_ref", "embedRef"]);
    if (embedRef) {
      lookup.set(embedRef, embedId);
      lookup.set(`embed:${embedRef}`, embedId);
    }
  }
  return lookup;
}

export function extractReferencedExampleEmbedIds(
  messages: Array<Pick<ExampleChatMessage, "content">>,
  embeds: ExampleChatEmbed[],
): string[] {
  const refLookup = buildEmbedRefLookup(embeds);
  const ids = new Set<string>();
  const jsonBlockRe = /```(?:json_embed|json)\s*([\s\S]*?)\s*```/g;
  const inlineEmbedRe = /embed:([a-zA-Z0-9_.:-]+)/g;
  for (const message of messages) {
    const content = message.content ?? "";
    for (const match of Array.from(content.matchAll(jsonBlockRe))) {
      try {
        const parsed = JSON.parse(match[1].trim()) as Record<string, unknown>;
        const embedId = cleanString(parsed.embed_id ?? parsed.embedId);
        const resolved = refLookup.get(embedId) ?? refLookup.get(`embed:${embedId}`) ?? embedId;
        if (resolved) ids.add(normalizeEmbedId(resolved));
      } catch {
        // Ignore malformed non-embed JSON blocks.
      }
    }
    for (const match of Array.from(content.matchAll(inlineEmbedRe))) {
      const rawRef = match[1];
      const resolved = refLookup.get(rawRef) ?? refLookup.get(`embed:${rawRef}`) ?? rawRef;
      if (resolved) ids.add(normalizeEmbedId(resolved));
    }
  }
  return Array.from(ids);
}

function expandEmbedIds(embedIds: string[], embeds: ExampleChatEmbed[]): string[] {
  const lookup = buildEmbedLookup(embeds);
  const seen = new Set<string>();
  const queue = [...embedIds.map(normalizeEmbedId)];
  while (queue.length > 0) {
    const embedId = queue.shift();
    if (!embedId || seen.has(embedId)) continue;
    seen.add(embedId);
    const embed = lookup.get(embedId);
    if (!embed) continue;
    const childIds = [
      ...(embed.embed_ids ?? []),
      ...extractEmbedIdsFromContent(embed.content),
    ];
    for (const childId of childIds) {
      const normalizedChildId = normalizeEmbedId(childId);
      if (normalizedChildId && !seen.has(normalizedChildId)) queue.push(normalizedChildId);
    }
  }
  return Array.from(seen);
}

export function getEmbedFileReferences(embed: ResolvableChatEmbed): ChatFileReference[] {
  const embedId = cleanString(embed.embed_id ?? embed.embedId ?? embed.id);
  if (!embedId) return [];
  const decoded = decodeEmbedContent(embed.content);
  const type = (
    stringField(decoded, ["type", "embed_type", "embedType"]) ||
    cleanString(embed.type) ||
    "file"
  ).toLowerCase();
  if (!FILE_LIKE_TYPES.has(type)) return [];

  const title = inferTitle(embedId, type, decoded, embed.content);
  const nodeType = inferNodeType(title, type);
  const url = urlForType(type, decoded);
  const mimeType = stringField(decoded, ["mime_type", "file_type", "mimeType"]);
  const createdAt = numberValue(embed.created_at ?? embed.createdAt) ?? 0;
  return [{
    embedId: normalizeEmbedId(embedId),
    contentRef: `embed:${normalizeEmbedId(embedId)}`,
    title,
    subtitle: labelForNodeType(nodeType, type),
    type,
    nodeType,
    iconName: iconNameForNodeType(nodeType),
    createdAt,
    updatedAt: createdAt,
    metadata: buildMetadata(nodeType, type, decoded),
    appId: stringField(decoded, ["app_id", "appId"]) || cleanString(embed.app_id ?? embed.appId) || null,
    skillId: stringField(decoded, ["skill_id", "skillId"]) || cleanString(embed.skill_id ?? embed.skillId) || null,
    url: url && isSupportedPublicUrl(url) ? url : null,
    mimeType: mimeType || null,
  }];
}

export function collectExampleChatFileReferences(
  embeds: ExampleChatEmbed[],
  messages: Array<Pick<ExampleChatMessage, "content">> = [],
): ChatFileReference[] {
  if (embeds.length === 0) return [];
  const lookup = buildEmbedLookup(embeds);
  const referencedIds = extractReferencedExampleEmbedIds(messages, embeds);
  const candidateIds = referencedIds.length > 0
    ? expandEmbedIds(referencedIds, embeds)
    : embeds.map((embed) => normalizeEmbedId(embed.embed_id));
  const rows: ChatFileReference[] = [];
  const seen = new Set<string>();
  for (const embedId of candidateIds) {
    const embed = lookup.get(embedId);
    if (!embed) continue;
    for (const row of getEmbedFileReferences(embed)) {
      const key = `${row.embedId}:${row.title}`.toLowerCase();
      if (seen.has(key)) continue;
      rows.push(row);
      seen.add(key);
    }
  }
  return rows;
}
