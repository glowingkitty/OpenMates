/**
 * Shared display metadata for generated image previews and fullscreens.
 * Prefers the provider and filename stored by the actual generation task.
 * Older assets retain their original indexed filename on display and download.
 * No storage credentials or image content enter these display-only helpers.
 */
import { getModelByNameOrId, getModelDisplayName } from '../../../utils/modelDisplayName';

/** Prefer the actual serving provider; registry metadata supports older embeds. */
export function imageGenerationAttribution(model?: string, provider?: string): string | undefined {
  const modelName = model ? getModelDisplayName(model) : '';
  const providerName = provider || (model ? getModelByNameOrId(model)?.provider_name : undefined);
  return [modelName, providerName].filter(Boolean).join(' · ') || undefined;
}

/** Legacy names match the original asset record instead of changing on download. */
export function imageGenerationFilename(content: Record<string, unknown>, embedId?: string): string | undefined {
  if (typeof content.filename === 'string' && content.filename.trim()) return content.filename;
  if (!embedId) return undefined;
  const files = content.files as { original?: { format?: string } } | undefined;
  const extension = files?.original?.format || content.output_filetype || 'png';
  if (typeof extension !== 'string' || !/^(png|jpg|jpeg|webp|svg)$/.test(extension)) return undefined;
  return `openmates_generated_image_${embedId.slice(0, 8)}.${extension}`;
}
