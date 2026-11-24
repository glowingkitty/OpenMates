import { describe, expect, it, vi } from 'vitest';
import { createLiveItemClient, type LiveItemTransport } from './liveItemClient';

function fakeTransport() {
	let sink: ((name: string, payload: unknown) => void) | null = null;
	const request = vi.fn(async () => true);
	const transport = { request, onEvent: (s) => { sink = s; return () => { sink = null; }; } } as LiveItemTransport;
	return { transport, request, push: (n: string, p: unknown) => sink?.(n, p) };
}

describe('liveItemClient', () => {
	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('forwards every call to the matching worker method', async () => {
		const { transport, request } = fakeTransport();
		const client = createLiveItemClient(transport);
		const bytes = new Uint8Array([1, 2]);
		await client.liveOpen('i', 'doc');
		await client.liveApplyMirrorUpdate('i', bytes);
		await client.liveApplyOp('i', { t: 'x' });
		await client.liveSetPresence('i', { kind_cursor: null });
		await client.liveClose('i');
		expect(request.mock.calls).toEqual([
			['liveOpen', { itemId: 'i', kind: 'doc' }],
			['liveApplyMirrorUpdate', { itemId: 'i', bytes }],
			['liveApplyOp', { itemId: 'i', op: { t: 'x' } }],
			['liveSetPresence', { itemId: 'i', presence: { kind_cursor: null, display_name: 'You' } }],
			['liveClose', { itemId: 'i' }],
		]);
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
	it('names the signed-in person in every presence and keeps a name the editor gave', async () => {
		const { transport, request } = fakeTransport();
		const client = createLiveItemClient(transport);
		await client.liveSetPresence('i', { cursor: { row_id: 'r1', col_id: 'c1' } });
		await client.liveSetPresence('i', { kind_cursor: null, display_name: 'Ana' });
		expect(request.mock.calls).toEqual([
			['liveSetPresence', { itemId: 'i', presence: { cursor: { row_id: 'r1', col_id: 'c1' }, display_name: 'You' } }],
			['liveSetPresence', { itemId: 'i', presence: { kind_cursor: null, display_name: 'Ana' } }],
		]);
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.access.roles
	it('passes the Team of a Project item with the open request', async () => {
		const { transport, request } = fakeTransport();
		const client = createLiveItemClient(transport);
		await client.liveOpen('i', 'doc', 'p', 't');
		expect(request.mock.calls).toEqual([['liveOpen', { itemId: 'i', kind: 'doc', projectId: 'p', teamId: 't' }]]);
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model,live-collab.saving.automatic
	it('delivers known worker events to subscribers and ignores unknown ones', () => {
		const { transport, push } = fakeTransport();
		const client = createLiveItemClient(transport);
		const onStatus = vi.fn();
		const stop = client.on('liveStatus', onStatus);
		push('liveStatus', { itemId: 'i', status: 'offline' });
		push('mystery', {});
		expect(onStatus).toHaveBeenCalledTimes(1);
		const onVersion = vi.fn();
		client.on('liveVersion', onVersion);
		push('liveVersion', { itemId: 'i', version: 3, text: '<p>a</p>' });
		expect(onVersion).toHaveBeenCalledWith({ itemId: 'i', version: 3, text: '<p>a</p>' });
		expect(onStatus).toHaveBeenCalledWith({ itemId: 'i', status: 'offline' });
		stop();
		push('liveStatus', { itemId: 'i', status: 'saved' });
		expect(onStatus).toHaveBeenCalledTimes(1);
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model,live-collab.saving.automatic
	it('never rejects for best-effort calls the core refused', async () => {
		const { transport, request } = fakeTransport();
		request.mockRejectedValue(new Error('local_session'));
		const client = createLiveItemClient(transport);
		await expect(client.liveSetPresence('i', { kind_cursor: null })).resolves.toBeUndefined();
		await expect(client.liveApplyMirrorUpdate('i', new Uint8Array([1]))).resolves.toBeUndefined();
		await expect(client.liveClose('i')).resolves.toBeUndefined();
		await expect(client.liveOpen('i', 'doc')).rejects.toThrow('local_session');
	});
});
