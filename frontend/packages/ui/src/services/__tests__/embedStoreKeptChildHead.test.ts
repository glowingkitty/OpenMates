// A synced or fetched row the core finds older than the stored child head of a
// generated image (`images-generate.revision.message-shows-its-version`) does not
// replace that head, but every other effect of the write still runs: the memory
// cache is dropped so readers see the stored head, and availability listeners
// are told. The core decision itself is faked here (Rust tests cover it).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const core = vi.hoisted(() => ({ kept: new Set<string>(), asked: [] as unknown[] }));
vi.mock('../rustCore/embeds/messageEmbedVersion', () => ({
	keptStoredHeads: async (rows: Array<{ embedId: string }>) => {
		core.asked.push(rows);
		return new Set(rows.map((row) => row.embedId).filter((id) => core.kept.has(id)));
	}
}));

import { EmbedStore, embedAvailabilityVersion } from '../embedStore';

const row = (version: number, content: string) => ({
	embed_id: 'image-1', parent_embed_id: 'parent-1', encrypted_type: 'image-type', encrypted_content: content,
	status: 'finished', hashed_chat_id: 'chat-hash', hashed_message_id: 'message-hash', hashed_user_id: 'owner',
	version_number: version, createdAt: 1700000000000, updatedAt: 1700000001000
});

beforeEach(() => {
	vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
	core.kept.clear();
	core.asked.length = 0;
});
afterEach(() => vi.unstubAllEnvs());

describe('stored child head kept over an older synced row', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('keeps the stored head, drops the memory copy and still notifies listeners', async () => {
		const store = new EmbedStore();
		await store.putEncrypted('embed:image-1', row(3, 'ciphertext-v3'), 'images-image' as never, undefined, undefined,
			{ skipMetadataExtraction: true });
		expect(core.asked).toHaveLength(1);
		expect(await store.getRawEntry('embed:image-1')).toMatchObject({ version_number: 3 });

		core.kept.add('image-1');
		const before = get(embedAvailabilityVersion);
		await store.putEncrypted('embed:image-1', row(2, 'ciphertext-v2'), 'app-skill-use' as never, undefined, undefined,
			{ skipMetadataExtraction: true });
		expect(get(embedAvailabilityVersion)).toBeGreaterThan(before);
		// The memory copy was dropped and the older row was never pinned. The unit
		// environment has no IndexedDB, so nothing readable is left (in the app the
		// reader falls through to the stored v3 head).
		expect(await store.getRawEntry('embed:image-1')).toBeNull();

		// A root row is never asked about.
		core.asked.length = 0;
		await store.putEncrypted('embed:root-1', { ...row(1, 'c'), embed_id: 'root-1', parent_embed_id: undefined },
			'app-skill-use' as never, undefined, undefined, { skipMetadataExtraction: true });
		expect(core.asked).toEqual([]);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('skips only the kept row of a batch', async () => {
		const store = new EmbedStore();
		await store.putEncrypted('embed:image-1', row(3, 'ciphertext-v3'), 'images-image' as never, undefined, undefined,
			{ skipMetadataExtraction: true });
		core.kept.add('image-1');
		await store.putEncryptedBatch([
			{ contentRef: 'embed:image-1', data: row(2, 'ciphertext-v2'), type: 'app-skill-use' as never },
			{ contentRef: 'embed:image-2', data: { ...row(1, 'other'), embed_id: 'image-2' }, type: 'app-skill-use' as never }
		]);
		expect(await store.getRawEntry('embed:image-1')).toBeNull();
		expect(await store.getRawEntry('embed:image-2')).toMatchObject({ version_number: 1, embed_id: 'image-2' });
	});
});
