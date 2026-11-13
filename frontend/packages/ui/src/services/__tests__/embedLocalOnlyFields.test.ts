// Local-only durability markers of image versions (`revision_pending_version`
// on a stored head, `server_confirmed` on a stored row; wire contract "Durability
// markers (local only, never sent)") never reach the server through the existing
// paths that turn a stored `embeds` row into a `store_embed` payload.
import { describe, expect, it } from 'vitest';
import { EmbedStore } from '../embedStore';

const LOCAL_ONLY = ['revision_pending_version', 'server_confirmed'];

async function storedPendingHead(store: EmbedStore, embedId: string): Promise<void> {
	await store.putEncrypted(`embed:${embedId}`, {
		embed_id: embedId, encrypted_type: 'image-type', encrypted_content: 'ciphertext-v2', status: 'finished',
		hashed_chat_id: 'chat-hash', hashed_message_id: 'message-hash', hashed_user_id: 'owner', version_number: 2,
		revision_pending_version: 2, server_confirmed: true, createdAt: 1700000000000, updatedAt: 1700000001000
	} as Record<string, unknown>, 'images-image', JSON.stringify({ type: 'image', filename: 'flame.svg' }));
}

describe('local-only revision markers', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('are not part of the store_embed payload built from a stored head', async () => {
		const store = new EmbedStore();
		await storedPendingHead(store, 'pending-image');
		const payload = await store.getPersistencePayload('pending-image');
		expect(payload).toMatchObject({ embed_id: 'pending-image', version_number: 2 });
		for (const field of LOCAL_ONLY) expect(payload).not.toHaveProperty(field);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('are not part of the store_embed payload of a child-list update', async () => {
		const store = new EmbedStore();
		await storedPendingHead(store, 'pending-parent');
		const payload = await store.updateChildEmbedIds('pending-parent', ['child-a']);
		expect(payload).toMatchObject({ embed_id: 'pending-parent', embed_ids: ['child-a'] });
		for (const field of LOCAL_ONLY) expect(payload).not.toHaveProperty(field);
	});
});
