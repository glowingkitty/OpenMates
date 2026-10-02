import { embedStore } from '../../services/embedStore';
import { generateEmbedKey, encryptWithEmbedKey } from '../../services/cryptoService';
import type { EmbedType } from '../../message_parsing/types';

export const rootId = '90000000-0000-4000-8000-000000000001';
export const childIds = ['90000000-0000-4000-8000-000000000002', '90000000-0000-4000-8000-000000000003'];
const emptyId = '90000000-0000-4000-8000-000000000004';
const onOpen = (id: string, parent: string) => window.dispatchEvent(new CustomEvent('apps-inline-preview-open', { detail: { id, parent } }));
export default { embedId: rootId, appId: 'web', skillId: 'search', onOpen };
export const variants = { empty: { embedId: emptyId, appId: 'web', skillId: 'search', onOpen } };

// Seed a synthetic encrypted graph using the same store/key path as a request.
export const ready = (async () => {
  const key = generateEmbedKey();
  for (const [id, type, content] of [
    [rootId, 'app_skill_use', { app_id: 'web', skill_id: 'search', query: 'Preview search', embed_ids: childIds, result_count: 2 }],
    [emptyId, 'app_skill_use', { app_id: 'web', skill_id: 'search', embed_ids: [], result_count: 0 }],
    ...childIds.map((id, index) => [id, 'website', { app_id: 'web', skill_id: 'search', title: `Preview page ${index + 1}`, url: `https://example.test/${index + 1}`, description: 'A normal website result preview.' }]),
  ] as Array<[string, 'app_skill_use' | 'website', Record<string, unknown>]>) {
    await embedStore.putEncrypted(`embed:${id}`, { embed_id: id, status: 'finished', is_private: true, encrypted_type: await encryptWithEmbedKey(type, key), encrypted_content: await encryptWithEmbedKey(JSON.stringify(content), key), createdAt: Date.now(), updatedAt: Date.now() }, type as EmbedType, undefined, { app_id: 'web', skill_id: 'search' });
    embedStore.setEmbedKeyInCache(id, key);
  }
})();
