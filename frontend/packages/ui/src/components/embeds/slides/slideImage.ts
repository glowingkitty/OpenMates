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

interface ImageFile {
  s3_key: string;
  aes_nonce?: string;
  encryption?: string;
}

export interface ResolvedSlideImage {
  url: string;
  /** s3 key for createImageUrlOwner retain/release. */
  cacheKey: string;
}

export async function resolveSlideImage(
  ref: string,
  chatId: string | null
): Promise<ResolvedSlideImage | null> {
  const embedId = embedStore.resolveByRef(ref) ?? ref;
  const embed = await resolveEmbed(embedId, { chatId: chatId ?? undefined });
  const content = embed?.content ? await decodeToonContent(embed.content) : null;
  if (!content) return null;
  const files = content.files as Record<string, ImageFile> | undefined;
  const file = files?.preview ?? files?.original;
  if (
    !file ||
    typeof content.s3_base_url !== 'string' ||
    typeof content.aes_key !== 'string' ||
    !hasMediaEncryptionMetadata(file, content.aes_nonce as string | undefined)
  ) {
    return null;
  }
  let url = getCachedImageUrl(file.s3_key);
  if (!url) {
    await fetchAndDecryptImage(content.s3_base_url, file.s3_key, content.aes_key, (content.aes_nonce as string) ?? '', file);
    url = getCachedImageUrl(file.s3_key);
  }
  return url ? { url, cacheKey: file.s3_key } : null;
}
