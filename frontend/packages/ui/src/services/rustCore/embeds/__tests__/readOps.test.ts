import { describe, expect, it } from 'vitest';
import { createEmbedReadHandlers } from '../readOps';

const SIGNAL = new AbortController().signal;
const binding = {
	embed_event_admitted(current: string, incoming: string | undefined, cv: number | undefined, iv: number | undefined, exempt: boolean): boolean {
		return `${current}>${incoming}:${cv}:${iv}:${exempt}` === 'processing>finished:undefined:undefined:false';
	},
	embed_apply_version_patch(content: string, patch: string): string {
		if (patch === 'bad') throw 'Version patch has no hunks';
		if (patch === 'fault') throw new Error('boom');
		return `${content}+${patch}`;
	}
};

describe('embedData read ops', () => {
	const handlers = createEmbedReadHandlers(binding);

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('applies patches per item and maps a Rust refusal to a fixed code', async () => {
		expect(await handlers.applyVersionPatches({ items: [{ content: 'a', patch: 'p' }, { content: 'a', patch: 'bad' }] }, SIGNAL))
			.toEqual([{ ok: true, content: 'a+p' }, { ok: false, code: 'version_patch_refused' }]);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses malformed requests and protocol faults', () => {
		expect(() => handlers.applyVersionPatches({ items: [{ content: 1 }] } as never, SIGNAL))
			.toThrow(expect.objectContaining({ code: 'embed_data_bad_request' }));
		expect(() => handlers.applyVersionPatches({ items: [{ content: 'a', patch: 'fault' }] }, SIGNAL))
			.toThrow(expect.objectContaining({ code: 'embed_data_failed' }));
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('marshals embed event admission facts to the binding and refuses malformed facts', () => {
		const facts = { currentStatus: 'processing', incomingStatus: 'finished', currentVersion: null, incomingVersion: null, versionExempt: false };
		expect(handlers.admitEmbedEvent(facts, SIGNAL)).toBe(true);
		expect(handlers.admitEmbedEvent({ ...facts, versionExempt: true }, SIGNAL)).toBe(false);
		expect(() => handlers.admitEmbedEvent({ ...facts, currentVersion: Number.NaN }, SIGNAL))
			.toThrow(expect.objectContaining({ code: 'embed_data_bad_request' }));
		expect(() => handlers.admitEmbedEvent({ ...facts, currentStatus: 1 } as never, SIGNAL))
			.toThrow(expect.objectContaining({ code: 'embed_data_bad_request' }));
	});
});
