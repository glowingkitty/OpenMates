import { expect, it, vi } from 'vitest';
import { EmbedStore } from '../embedStore';
import { chatDB } from '../db';

// contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
it('rechecks the account after async IDB setup and before the encrypted row write', async () => {
  const store = new EmbedStore();
  let resumeTransaction!: (transaction: IDBTransaction) => void;
  const pendingTransaction = new Promise<IDBTransaction>((resolve) => { resumeTransaction = resolve; });
  const put = vi.fn();
  vi.spyOn(chatDB, 'getTransaction').mockReturnValueOnce(pendingTransaction);
  let currentUser = 'account-a';
  const operation = store.putEncrypted(
    'embed:account-a-result',
    { embed_id: 'account-a-result', encrypted_type: '<type>', encrypted_content: '<cipher>', status: 'finished' },
    'app_skill_use', undefined, { app_id: 'events', skill_id: 'search' },
    { skipMetadataExtraction: true, writeGuard: () => {
      if (currentUser !== 'account-a') throw new Error('account changed');
    } },
  );
  await vi.waitFor(() => expect(chatDB.getTransaction).toHaveBeenCalled());
  currentUser = 'account-b';
  resumeTransaction({ objectStore: () => ({ put }) } as unknown as IDBTransaction);
  await expect(operation).rejects.toThrow('account changed');
  expect(put).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});
