import { describe, expect, it } from 'vitest';
import { createEmbedReadHandlers } from '../readOps';

const SIGNAL = new AbortController().signal;
const binding = {
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
});
