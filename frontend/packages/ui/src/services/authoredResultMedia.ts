import type { AuthoredResultMedia } from '../types/authoredResult';
import {
  createImageUrlOwner,
  fetchAndDecryptImage,
  getCachedImageUrl,
} from '../components/embeds/images/imageEmbedCrypto';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';

export interface AuthoredResultMediaView {
  url: string;
  caption?: string;
  attribution?: string;
}

export type AuthoredResultMediaSize = 'preview' | 'fullscreen';

/**
 * One mounted presentation owns one resolver. Pass only its selected encrypted
 * authored_media descriptors, never public image URLs or an embed graph. Each
 * resolve replaces the previous set; dispose on unmount. Old calls resolve to []
 * after an update, disposal or account/workspace change. Recreate on that change.
 *
 * URLs live only in the existing in-memory image cache and its reference-counted
 * grace period. Never save the returned blob URLs in embed content or storage.
 */
export function createAuthoredResultMediaOwner() {
  const epoch = getWorkspaceCacheEpoch();
  let generation = 0;
  let disposed = false;
  let owner: ReturnType<typeof createImageUrlOwner> | undefined;

  return {
    async resolve(
      authoredMedia: readonly AuthoredResultMedia[] | null | undefined,
      size: AuthoredResultMediaSize = 'preview',
    ): Promise<AuthoredResultMediaView[]> {
      const request = ++generation;
      owner?.destroy();
      owner = undefined;
      const active = () => !disposed && request === generation && epoch === getWorkspaceCacheEpoch();
      if (!active() || !Array.isArray(authoredMedia)) return [];

      const requestOwner = createImageUrlOwner();
      owner = requestOwner;
      const variants = size === 'fullscreen'
        ? ['original', 'full', 'preview'] as const
        : ['preview', 'full', 'original'] as const;
      const resolved = await Promise.all(authoredMedia.map(async (media): Promise<AuthoredResultMediaView | undefined> => {
        if (!media || typeof media.source_embed_id !== 'string' || !media.source_embed_id.trim()
          || typeof media.s3_base_url !== 'string' || typeof media.aes_key !== 'string' || !media.aes_key.trim()
          || !media.files || typeof media.files !== 'object' || Array.isArray(media.files)) return;
        const file = variants.map(variant => media.files[variant])
          .find(candidate => candidate && typeof candidate.s3_key === 'string' && candidate.s3_key.trim());
        if (!file || !active()) return;
        const key = file.s3_key;
        try {
          let url = getCachedImageUrl(key);
          if (!url) {
            await fetchAndDecryptImage(
              media.s3_base_url, key, media.aes_key,
              typeof media.aes_nonce === 'string' ? media.aes_nonce : '', file,
            );
            if (!active()) return;
            url = getCachedImageUrl(key);
          }
          if (!url || !active()) return;
          requestOwner.retain(key);
          return {
            url,
            ...(typeof media.caption === 'string' ? { caption: media.caption } : {}),
            ...(typeof media.attribution === 'string' ? { attribution: media.attribution } : {}),
          };
        } catch {
          // An unavailable image must not hide the readable card or other media.
          return;
        }
      }));
      if (!active()) {
        requestOwner.destroy();
        return [];
      }
      return resolved.filter((media): media is AuthoredResultMediaView => media !== undefined);
    },
    dispose(): void {
      disposed = true;
      generation++;
      owner?.destroy();
      owner = undefined;
    },
  };
}
