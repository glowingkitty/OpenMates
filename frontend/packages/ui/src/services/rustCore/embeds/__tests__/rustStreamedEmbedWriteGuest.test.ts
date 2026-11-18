// A signed-out guest chat's finalized embed goes to the local-only guest writer, never the account writer or the server.
import { describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
	const unit = { request: vi.fn(async (name: string) => {
		if (name === 'prepareStreamCompletion') {
			return { embed_ref_registration: null, child_ref_embed_ids: [], local_entry: { contentRef: 'ref' }, store_payload: null, server_keys: null };
		}
		return null;
	}) };
	return { unit, account: vi.fn(), guest: vi.fn(async () => ({ unit })), sendStoreEmbed: vi.fn() };
});
const { unit, account, guest, sendStoreEmbed } = h;

vi.mock('../embedWriteSession', () => ({ rustEmbedWriter: h.account, rustGuestEmbedWriter: h.guest }));
vi.mock('../../crypto/webCryptoClient', () => ({ rustWebCrypto: () => ({}) }));
vi.mock('../../../db', () => ({ chatDB: { getChat: async () => null } }));
vi.mock('../../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKeySync: () => new Uint8Array(32), getKey: async () => new Uint8Array(32) } }));
vi.mock('../../../../message_parsing/utils', () => ({ computeSHA256: async () => 'hash' }));
vi.mock('../embedDataClient', () => ({ rustEmbedData: () => undefined }));
vi.mock('../rustChildRevisionWrite', () => ({ childRevisionIO: vi.fn(), isChildRevisionEvent: () => false, runChildRevision: vi.fn() }));
vi.mock('../../../chatSyncServiceSenders', () => ({ sendStoreEmbedImpl: h.sendStoreEmbed }));
vi.mock('../../../embedStore', () => ({
	embedStore: { registerEmbedRef: vi.fn(), removeFromMemoryCache: vi.fn(), clearUploadedFileSearchCache: vi.fn(), get: vi.fn() },
	embedAvailabilityVersion: { update: vi.fn() }
}));
vi.mock('../../../../data/embedRegistry.generated', () => ({ normalizeEmbedType: (type: string) => type }));

import { writeStreamedEmbedInRust } from '../rustStreamedEmbedWrite';

describe('guest streamed embed write', () => {
	// contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content
	it('routes an anonymous chat embed to the guest writer as local-only', async () => {
		const service = { dispatchEvent: vi.fn() };
		const embedData = { embed_id: 'e1', chat_id: 'anonymous-chat', type: 'app_skill_use', status: 'finished', user_id: 'u', embed_ids: [] };
		await expect(writeStreamedEmbedInRust(service as never, embedData as never, {} as never, false)).resolves.toBe(true);
		expect(account).not.toHaveBeenCalled();
		expect(guest).toHaveBeenCalledOnce();
		expect(unit.request).toHaveBeenCalledWith('prepareStreamCompletion', expect.objectContaining({
			payload: expect.objectContaining({ local_only: true })
		}));
		expect(sendStoreEmbed).not.toHaveBeenCalled();
	});
});
