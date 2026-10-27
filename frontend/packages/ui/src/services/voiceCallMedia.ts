import { embedStore } from './embedStore';
import { decodeToonContent } from './embedResolver';
import { generatedMediaChildIds, isGeneratedMediaSkill } from '../components/embeds/generatedMediaGroup';
import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from '../components/embeds/images/imageEmbedCrypto';
import { createAudioUrlOwner } from '../components/embeds/audio/audioEmbedCrypto';
import { hasMediaEncryptionMetadata } from './encryption/mediaEncryption';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';

export interface VoiceCallDisplayedMedia { embedId: string; kind: 'image' | 'video'; url: string }

/** A call owns its plaintext URLs; delayed decryptions cannot outlive the owner. */
export function createVoiceCallMediaResolver() {
  const images = new Set<string>();
  const videos = createAudioUrlOwner();
  const epoch = getWorkspaceCacheEpoch();
  let disposed = false;
  let generation = 0;
  const alive = () => !disposed && epoch === getWorkspaceCacheEpoch();
  return {
    async resolve(embedIds: string[]): Promise<VoiceCallDisplayedMedia[]> {
      const request = ++generation;
      const media: VoiceCallDisplayedMedia[] = [];
      const pending = [...embedIds];
      const seen = new Set<string>();
      while (pending.length && seen.size < 64 && alive() && request === generation) {
        const id = pending.shift()!;
        if (seen.has(id)) continue;
        seen.add(id);
        const embed = await embedStore.get(`embed:${id}`);
        if (!alive() || request !== generation) break;
        if (!embed || typeof embed !== 'object' || embed._decryptionFailed || embed._decryptionPending) continue;
        const content = typeof embed.content === 'string' ? await decodeToonContent(embed.content)
          : embed.content && typeof embed.content === 'object' && !Array.isArray(embed.content)
            ? embed.content as Record<string, unknown> : null;
        if (!content || !alive() || request !== generation) continue;
        const app = content.app_id ?? embed.app_id;
        const skill = content.skill_id ?? embed.skill_id;
        const type = content.type ?? embed.type ?? embed.embed_type;
        const children = generatedMediaChildIds(content);
        if (children.length && isGeneratedMediaSkill(app, skill)) { pending.push(...children); continue; }
        const kind = type === 'generated_image' || app === 'images' && isGeneratedMediaSkill(app, skill) ? 'image'
          : type === 'generated_video' || app === 'videos' && skill === 'generate' ? 'video' : null;
        if (!kind || (content.status ?? embed.status) !== 'finished') continue;
        const files = content.files as Record<string, Record<string, unknown>> | undefined;
        const file = files?.original ?? (kind === 'image' ? files?.preview : undefined);
        const key = file?.s3_key;
        const base = content.s3_base_url;
        const aes = content.aes_key;
        const nonce = typeof content.aes_nonce === 'string' ? content.aes_nonce : '';
        if (!file || typeof key !== 'string' || typeof base !== 'string' || typeof aes !== 'string' ||
          !hasMediaEncryptionMetadata(file, nonce)) continue;
        let url: string | undefined;
        if (kind === 'image') {
          await fetchAndDecryptImage(base, key, aes, nonce, file);
          if (!alive() || request !== generation) continue;
          url = getCachedImageUrl(key);
          if (url && !images.has(key)) { retainCachedImage(key); images.add(key); }
        } else {
          url = await videos.fetch(base, key, aes, nonce, typeof file.mime_type === 'string' ? file.mime_type : 'video/mp4', file);
        }
        if (url && alive() && request === generation) media.push({ embedId: id, kind, url });
      }
      return alive() && request === generation ? media : [];
    },
    destroy(): void {
      disposed = true;
      generation++;
      for (const key of images) releaseCachedImage(key);
      images.clear();
      videos.destroy();
    },
  };
}
