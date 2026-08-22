/**
 * frontend/packages/ui/src/services/generatedAudioExport.ts
 *
 * Shared helpers for downloadable public generated-audio fixtures.
 * Example chats keep static MP3s under /store-examples and reference them from
 * app_skill_use TOON content via previewAudioUrl. Private generated media stays
 * on the encrypted S3 path and is intentionally not inferred from arbitrary URLs.
 */

export interface StaticGeneratedAudioDownload {
  filename: string;
  url: string;
  mimeType: string;
  durationSeconds?: number;
  sizeBytes?: number;
}

const STATIC_AUDIO_URL_RE = /^\/store-examples\/[^?#]+\.(?:mp3|m4a|wav|ogg|webm)(?:[?#].*)?$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cleanString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || value.trim() === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function stripToonQuotes(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

export function parseFlatToonFields(content: string): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const line of content.split('\n')) {
    if (!line || /^\s/.test(line)) continue;
    const separatorIndex = line.indexOf(':');
    if (separatorIndex <= 0) continue;
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    if (!key || !value) continue;
    fields[key] = stripToonQuotes(value);
  }
  return fields;
}

export function staticAudioFilenameFromUrl(url: string): string {
  const withoutQuery = url.split(/[?#]/)[0] || '';
  const basename = withoutQuery.split('/').pop() || 'generated-audio.mp3';
  return basename.replace(/[^a-zA-Z0-9._-]/g, '_') || 'generated-audio.mp3';
}

export function getStaticGeneratedAudioDownload(
  content: Record<string, unknown> | string | null | undefined,
): StaticGeneratedAudioDownload | null {
  const decoded = typeof content === 'string' ? parseFlatToonFields(content) : content;
  if (!isRecord(decoded)) return null;

  const appId = cleanString(decoded.app_id);
  const skillId = cleanString(decoded.skill_id);
  if (appId !== 'audio' || (skillId !== 'generate' && skillId !== 'speak')) return null;

  const url = cleanString(decoded.previewAudioUrl) || cleanString(decoded.preview_audio_url);
  if (!STATIC_AUDIO_URL_RE.test(url)) return null;

  const files = isRecord(decoded.files) ? decoded.files : null;
  const original = files && isRecord(files.original) ? files.original : null;
  const filename = cleanString(decoded.filename) || staticAudioFilenameFromUrl(url);
  const mimeType = cleanString(decoded.mime_type) || cleanString(original?.mime_type) || 'audio/mpeg';

  return {
    filename: filename.replace(/[/\\]/g, '_'),
    url,
    mimeType,
    durationSeconds: numberValue(decoded.duration_seconds) ?? numberValue(original?.duration_seconds),
    sizeBytes: numberValue(decoded.byte_length) ?? numberValue(original?.size_bytes),
  };
}
