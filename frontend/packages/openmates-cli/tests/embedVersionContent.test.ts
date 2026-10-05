import { it } from 'node:test';
import assert from 'node:assert/strict';
import { OpenMatesClient } from '../src/client.ts';
import { encryptWithAesGcmCombined } from '../src/crypto.ts';

function clientFor(rows: unknown[], version = 2) {
	const client = Object.create(OpenMatesClient.prototype) as Record<string, any>;
	const key = new Uint8Array(32).fill(7);
	client.resolveEmbedId = async () => 'embed-1';
	client.resolveVersionEmbedKey = async () => key;
	client.getCliRequestHeaders = () => ({});
	client.http = { get: async () => ({ ok: true, status: 200, data: {
		embed_id: 'embed-1', version_number: version, current_version: 2, readonly: false, rows,
	} }) };
	return { client, key };
}

// contract-test: direct surface=cli assertions=storage.versions.bounded-reconstruction
it('decrypts an exact version with a zero-count insertion at the beginning', async () => {
	const { client, key } = clientFor([]);
	client.http.get = async () => ({ ok: true, status: 200, data: {
		embed_id: 'embed-1', version_number: 2, current_version: 2, readonly: false,
		rows: [{ version_number: 1, encrypted_snapshot: await encryptWithAesGcmCombined('first\nlast', key) },
			{ version_number: 2, encrypted_patch: await encryptWithAesGcmCombined('@@ -0,0 +1 @@\n+new', key) }],
	} });
	assert.equal((await client.getEmbedVersion('embed-1', 2)).content, 'new\nfirst\nlast');
});

// contract-test: direct surface=cli assertions=storage.versions.bounded-reconstruction
it('rejects a response for a different target and a version missing its patch', async () => {
	const { client, key } = clientFor([{ version_number: 1 }], 1);
	await assert.rejects(client.getEmbedVersion('embed-1', 2), /does not match the selected version/);
	client.http.get = async () => ({ ok: true, status: 200, data: {
		embed_id: 'embed-1', version_number: 2, current_version: 2, readonly: false,
		rows: [{ version_number: 1, encrypted_snapshot: await encryptWithAesGcmCombined('first', key) },
			{ version_number: 2 }],
	} });
	await assert.rejects(client.getEmbedVersion('embed-1', 2), /Version patch is missing/);
});
