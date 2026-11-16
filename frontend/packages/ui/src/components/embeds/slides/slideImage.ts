/**
 * frontend/packages/ui/src/components/embeds/slides/slideImage.ts
 *
 * Resolves an `embed:<ref>` image of a slide to a displayable blob URL through
 * the existing embed resolver and image decrypt utilities (the same path the
 * skill input thumbnails use). Returns null when the embed is not available
 * (not synced yet, no encryption metadata); the canvas then shows a neutral
 * placeholder. Never fetches arbitrary URLs.
 */

import { embedStore } from '../../../services/embedStore';
import { resolveEmbed, decodeToonContent } from '../../../services/embedResolver';
import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
import { fetchAndDecryptImage, getCachedImageUrl } from '../images/imageEmbedCrypto';

export interface ImageFile {
  s3_key: string;
  aes_nonce?: string;
  encryption?: string;
  format?: string;
  sanitized?: boolean;
}

export interface ResolvedSlideImage {
  /** Still raster picture (always set). */
  url: string;
  /** s3 key for createImageUrlOwner retain/release. */
  cacheKey: string;
  /** Sanitized SVG whose declarative animation may play; absent for still-only images. */
  animatedUrl?: string;
  animatedCacheKey?: string;
}

/**
 * Chooses the still raster and the optional animated SVG variant of an image
 * embed. Only a variant the backend marked `sanitized: true` is ever returned as
 * animated (uploads: `files.vector`, generated SVGs: `files.original`).
 */
export function pickSlideImageVariants(
  content: Record<string, unknown>
): { still: ImageFile | null; animated: ImageFile | null } {
  const files = content.files as Record<string, ImageFile> | undefined;
  const isSvg = (f?: ImageFile): f is ImageFile => !!f && f.format === 'svg' && f.sanitized === true;
  const animated = isSvg(files?.vector) ? files.vector : isSvg(files?.original) ? files.original : null;
  const rasterOriginal = files?.original && files.original.format !== 'svg' ? files.original : undefined;
  const still = files?.preview ?? rasterOriginal ?? null;
  return { still, animated };
}

async function loadVariant(
  content: Record<string, unknown>,
  file: ImageFile
): Promise<string | null> {
  if (
    typeof content.s3_base_url !== 'string' ||
    typeof content.aes_key !== 'string' ||
    !hasMediaEncryptionMetadata(file, content.aes_nonce as string | undefined)
  ) {
    return null;
  }
  let url = getCachedImageUrl(file.s3_key);
  if (!url) {
    await fetchAndDecryptImage(content.s3_base_url, file.s3_key, content.aes_key, (content.aes_nonce as string) ?? '', file, file.format);
    url = getCachedImageUrl(file.s3_key);
  }
  return url ?? null;
}

export async function resolveSlideImage(
  ref: string,
  chatId: string | null
): Promise<ResolvedSlideImage | null> {
  const embedId = embedStore.resolveByRef(ref) ?? ref;
  const embed = await resolveEmbed(embedId, { chatId: chatId ?? undefined });
  const content = embed?.content ? await decodeToonContent(embed.content) : null;
  if (!content) return null;
  const { still, animated } = pickSlideImageVariants(content);
  const stillUrl = still ? await loadVariant(content, still) : null;
  if (!still || !stillUrl) return null;
  const resolved: ResolvedSlideImage = { url: stillUrl, cacheKey: still.s3_key };
  if (animated) {
    const animatedUrl = await loadVariant(content, animated);
    if (animatedUrl) {
      resolved.animatedUrl = animatedUrl;
      resolved.animatedCacheKey = animated.s3_key;
    }
  }
  return resolved;
}
