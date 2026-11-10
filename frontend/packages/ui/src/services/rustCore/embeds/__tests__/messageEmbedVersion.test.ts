// Message-scoped image versions on the web shell: a card whose message pins a
// version newer than this device's head re-resolves once the head arrives,
// also when it arrives through a store write that dispatches no
// `embedUpdated` (sync, server read), and synced rows ask the core whether a
// stored child head is kept. The Worker unit is an in-memory fake; the
// version rules themselves are the core's (Rust tests).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';

const fake = vi.hoisted(() => ({
	head: 2 as number | null,
	kept: [] as string[],
	requests: [] as Array<{ op: string; payload: unknown }>
}));

vi.mock('../embedWriteSession', () => ({
	rustEmbedWriter: async () => ({
		unit: {
			closed: false,
			async request(op: string, payload: Record<string, unknown>) {
				fake.requests.push({ op, payload });
				if (op === 'embedHeadVersion') return fake.head === null ? null : { version: fake.head, parent_embed_id: 'parent-1' };
				if (op === 'embedVersionsByMessage') {
					// Core rule stand-in: m3's parent pins v3, m1 created v1.
					const messages = payload.messages as Array<{ message_id: string; parent_contents: string[] }>;
					return messages.map((message) => ({
						message_id: message.message_id,
						version: message.parent_contents.some((content) => content.includes('pinned_embeds')) ? 3 : 1,
						pinned_here: message.parent_contents.length > 0
					}));
				}
				if (op === 'embedSyncedHeadsKept') return fake.kept;
				throw new Error(`unexpected ${op}`);
			}
		}
	}),
	onRustEmbedWriterClosed: () => {}
}));

const availability = vi.hoisted(() => ({ store: null as null | ReturnType<typeof writable<number>> }));
vi.mock('../../../embedStore', async () => {
	const { writable: make } = await import('svelte/store');
	availability.store = make(0);
	return { embedAvailabilityVersion: availability.store };
});
vi.mock('../../../chatSyncService', () => ({ chatSyncService: new EventTarget() }));
vi.mock('../../../embedResolver', () => ({
	extractEmbedReferences: (markdown: string) => markdown.includes('parent-3') ? [{ type: 'app_skill_use', embed_id: 'parent-3' }] : [],
	resolveEmbed: async (id: string) => id === 'parent-3' ? { content: 'pinned_embeds[1]{embed_id,version}:\n  image-1,3' } : null
}));

type Module = typeof import('../messageEmbedVersion');
let mod: Module;

const MESSAGES = [
	{ id: 'm1', original_message: { content: 'created' } },
	{ id: 'm3', original_message: { content: '```json\n{"type":"app_skill_use","embed_id":"parent-3"}\n```' } }
];

async function publishedChat(): Promise<void> {
	mod.publishChatMessageOrder('chat-1', MESSAGES);
	// The store subscription is installed after two dynamic imports; the
	// message-order refresh (debounced) bumps once on its own.
	await vi.waitFor(() => expect(availability.store).not.toBeNull());
	await new Promise((resolve) => setTimeout(resolve, 300));
}

beforeEach(async () => {
	vi.resetModules();
	vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
	availability.store = null;
	fake.head = 2;
	fake.kept = [];
	fake.requests.length = 0;
	mod = await import('../messageEmbedVersion');
});

afterEach(() => {
	vi.unstubAllEnvs();
});

describe('messageEmbedVersion', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('re-resolves a card waiting for a newer head once a store write brings that head', async () => {
		await publishedChat();
		expect(await mod.embedVersionForMessage('m3', 'image-1')).toEqual({ version: 3, headVersion: 2, pinnedHere: true });
		const before = get(mod.embedVersionGeneration);

		// A store change that leaves the head below the pin does not re-resolve cards.
		availability.store!.update((value) => value + 1);
		await new Promise((resolve) => setTimeout(resolve, 350));
		expect(get(mod.embedVersionGeneration)).toBe(before);

		// The head reaches v3 through a write without `embedUpdated`: cards re-resolve and show it.
		fake.head = 3;
		availability.store!.update((value) => value + 1);
		await vi.waitFor(() => expect(get(mod.embedVersionGeneration)).toBeGreaterThan(before), { timeout: 2000 });
		expect(await mod.embedVersionForMessage('m3', 'image-1')).toEqual({ version: 3, headVersion: 3, pinnedHere: true });
		// Nothing is waited for any more: further store writes do not bump again.
		const settled = get(mod.embedVersionGeneration);
		availability.store!.update((value) => value + 1);
		await new Promise((resolve) => setTimeout(resolve, 350));
		expect(get(mod.embedVersionGeneration)).toBe(settled);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('asks the core which stored child heads a synced row must not replace', async () => {
		fake.kept = ['image-1'];
		const rows = [{ embedId: 'image-1', incoming: { embed_id: 'image-1', parent_embed_id: 'parent-1', version_number: 2 } }];
		expect([...(await mod.keptStoredHeads(rows))]).toEqual(['image-1']);
		expect(fake.requests).toContainEqual({ op: 'embedSyncedHeadsKept', payload: { rows } });
		// Nothing to compare: no Worker request.
		fake.requests.length = 0;
		expect((await mod.keptStoredHeads([])).size).toBe(0);
		expect(fake.requests).toEqual([]);
	});
});
