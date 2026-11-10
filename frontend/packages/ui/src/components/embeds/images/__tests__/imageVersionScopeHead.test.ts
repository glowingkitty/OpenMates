// What a message's image card shows once the head it waited for arrived: the
// head's own content is opened through the core, because the card's mount data
// belongs to an older version. The version rule itself is the core's.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const core = vi.hoisted(() => ({
	resolved: { version: 3, headVersion: 3, pinnedHere: true } as { version: number; headVersion: number; pinnedHere: boolean } | null,
	opened: [] as Array<{ chatId: string; embedId: string; version: number }>
}));

vi.mock('../../../../services/rustCore/embeds/messageEmbedVersion', () => ({
	EMBED_VERSIONS_ENABLED: true,
	embedVersionForMessage: async () => core.resolved,
	embedContentAtVersion: async (chatId: string, embedId: string, version: number) => {
		core.opened.push({ chatId, embedId, version });
		return `toon-v${version}`;
	},
	messageIdOf: () => null,
	publishedChatId: () => 'chat-1'
}));
vi.mock('../../../../services/embedResolver', () => ({
	decodeToonContent: async (toon: string) => ({ files: { preview: { s3_key: `${toon}.webp` } } })
}));

import { resolveImageVersionView } from '../imageVersionScope';

beforeEach(() => {
	core.opened.length = 0;
	core.resolved = { version: 3, headVersion: 3, pinnedHere: true };
});

describe('resolveImageVersionView after waiting for the head', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('opens the head content only for a card that waited for it', async () => {
		// An ordinary card at the head keeps its own data.
		expect(await resolveImageVersionView('m3', 'image-1', null)).toEqual({ version: 3, headVersion: 3, waitingForHead: false, content: null });
		expect(core.opened).toEqual([]);
		// A card that waited for v3 shows v3's own files, not its mount data.
		expect(await resolveImageVersionView('m3', 'image-1', null, { headContent: true })).toEqual({
			version: 3, headVersion: 3, waitingForHead: false, content: { files: { preview: { s3_key: 'toon-v3.webp' } } }
		});
		expect(core.opened).toEqual([{ chatId: 'chat-1', embedId: 'image-1', version: 3 }]);
		// Still below the pin: it keeps waiting and opens nothing.
		core.resolved = { version: 4, headVersion: 3, pinnedHere: true };
		core.opened.length = 0;
		expect(await resolveImageVersionView('m4', 'image-1', null, { headContent: true })).toMatchObject({ waitingForHead: true, content: null });
		expect(core.opened).toEqual([]);
	});
});
