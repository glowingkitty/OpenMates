import { embedStore } from '../../services/embedStore';
import { generateEmbedKey, encryptWithEmbedKey } from '../../services/cryptoService';
import { authStore } from '../../stores/authStore';
import type { EmbedType } from '../../message_parsing/types';

export const codeIds = ['91000000-0000-4000-8000-000000000001', '91000000-0000-4000-8000-000000000002'];
export const searchId = '91000000-0000-4000-8000-000000000003';
const childId = '91000000-0000-4000-8000-000000000004';
const onClose = () => window.dispatchEvent(new Event('standalone-preview-close'));
export default { embedId: codeIds[0], appId: 'code', onClose };
export const variants = { search: { embedId: searchId, appId: 'web', onClose } };
export const layout = 'fill';

// Keep the actual encryption, app index, resolver and renderer path in the
// account-free preview. No ActiveChat/fullscreen event listener is mounted.
export const ready = (async () => {
  authStore.set({ isAuthenticated: false, isInitialized: true });
  const key = generateEmbedKey();
  const fixtures: Array<[string, string, Record<string, unknown>]> = [
    ...codeIds.map((id, index): [string, string, Record<string, unknown>] => [id, 'code', {
      app_id: 'code', filename: `Library ${index + 1}.py`, language: 'python',
      code: `library_value = ${42 + index}\nprint(library_value)`, line_count: 2,
    }]),
    [searchId, 'app_skill_use', { app_id: 'web', skill_id: 'search', query: 'Library search',
      embed_ids: [childId], result_count: 1 }],
    [childId, 'search_result', { type: 'search_result', app_id: 'web', skill_id: 'search',
      title: 'Original library result', url: 'https://example.test/library', description: 'Original child details' }],
  ];
  for (const [id, type, content] of fixtures) {
    await embedStore.putEncrypted(`embed:${id}`, {
      embed_id: id, status: 'finished', is_private: true,
      encrypted_type: await encryptWithEmbedKey(type, key),
      encrypted_content: await encryptWithEmbedKey(JSON.stringify(content), key),
      createdAt: Date.now(), updatedAt: Date.now(),
    }, type as EmbedType, undefined, { app_id: content.app_id as string, skill_id: content.skill_id as string | undefined });
    embedStore.setEmbedKeyInCache(id, key);
  }
})();
