/**
 * frontend/packages/ui/src/components/embeds/audio/audioGeneratedEmbedContent.ts
 *
 * Shared normalizers for generated audio app-skill embeds.
 * Direct app-skill results may arrive as flattened results[0] fields, while
 * async/generated media tasks expose nested files.original metadata.
 * This keeps the player components independent of the backend serialization path.
 */

export type AudioSkillId = 'generate' | 'speak';

export interface GeneratedAudioFileVariant {
  s3_key: string;
  size_bytes?: number;
  format?: string;
  mime_type?: string;
  duration_seconds?: number;
  encryption?: string;
}

export interface GeneratedAudioFiles {
  original?: GeneratedAudioFileVariant;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function normalizeAudioSkillId(value: unknown): AudioSkillId {
  return value === 'speak' ? 'speak' : 'generate';
}

export function resolveGeneratedAudioContent(
  content: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!content) return {};
  const results = content.results;
  if (Array.isArray(results)) {
    const firstResult = results.find(isRecord);
    if (firstResult) {
      return { ...content, ...firstResult };
    }
  }
  return content;
}

export function getStringField(
  content: Record<string, unknown>,
  fields: string[],
): string {
  for (const field of fields) {
    const value = content[field];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  return '';
}

export function getNumberField(
  content: Record<string, unknown>,
  fields: string[],
): number | undefined {
  for (const field of fields) {
    const value = content[field];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return undefined;
}

export function getGeneratedAudioFiles(
  content: Record<string, unknown>,
): GeneratedAudioFiles | undefined {
  if (isRecord(content.files)) {
    return content.files as GeneratedAudioFiles;
  }

  const s3Key = getStringField(content, ['files_original_s3_key']);
  if (!s3Key) return undefined;

  return {
    original: {
      s3_key: s3Key,
      size_bytes: getNumberField(content, ['files_original_size_bytes']),
      format: getStringField(content, ['files_original_format']) || undefined,
      mime_type: getStringField(content, ['files_original_mime_type']) || undefined,
      duration_seconds: getNumberField(content, ['files_original_duration_seconds']),
      encryption: getStringField(content, ['files_original_encryption']) || undefined,
    },
  };
}

export function getGeneratedAudioDataUrl(
  content: Record<string, unknown>,
): string {
  const audioBase64 = getStringField(content, ['audio_base64']);
  if (!audioBase64) return '';
  const mimeType = getStringField(content, ['mime_type']) || 'audio/mpeg';
  return `data:${mimeType};base64,${audioBase64}`;
}
