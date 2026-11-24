// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import * as Y from 'yjs';
import { bindLiveMirror } from './liveMirror';
import { createLiveItemClient, type LiveItemTransport } from './liveItemClient';

function fakeClient() {
	let sink: ((name: string, payload: unknown) => void) | null = null;
	const request = vi.fn(async () => true);
	const transport = { request, onEvent: (s) => { sink = s; return () => { sink = null; }; } } as LiveItemTransport;
	return { client: createLiveItemClient(transport), request, push: (n: string, p: unknown) => sink?.(n, p) };
}

const mirrorCalls = (request: ReturnType<typeof vi.fn>) =>
	request.mock.calls.filter(([name]) => name === 'liveApplyMirrorUpdate');

describe('bindLiveMirror', () => {
	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model,live-collab.saving.automatic
	it('keeps typing done before the core holds the item and sends it once the core state arrives', async () => {
		const { client, request, push } = fakeClient();
		const mirror = bindLiveMirror(client, 'item-1', 'doc', { display_name: 'Mara', color: '#f00' });
		mirror.doc.getText('t').insert(0, 'early words');
		await Promise.resolve();
		expect(mirrorCalls(request)).toHaveLength(0);

		// The core's first full state: stored content from another replica.
		const stored = new Y.Doc();
		stored.getText('t').insert(0, 'stored ');
		push('liveRemoteUpdate', { itemId: 'item-1', bytes: Y.encodeStateAsUpdate(stored) });
		await Promise.resolve();

		const sent = mirrorCalls(request);
		expect(sent).toHaveLength(1);
		const core = new Y.Doc();
		Y.applyUpdate(core, Y.encodeStateAsUpdate(stored));
		Y.applyUpdate(core, (sent[0][1] as { bytes: Uint8Array }).bytes);
		expect(core.getText('t').toString()).toContain('early words');
		expect(core.getText('t').toString()).toContain('stored');

		// After the first state, typing goes straight through.
		mirror.doc.getText('t').insert(0, 'x');
		await Promise.resolve();
		expect(mirrorCalls(request)).toHaveLength(2);
		mirror.destroy();
	});
});
