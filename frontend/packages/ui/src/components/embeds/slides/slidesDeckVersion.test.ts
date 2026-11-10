/**
 * Unit tests for saving a manually edited deck as the next embed version: no write
 * for an unchanged deck, the exact base version/markup and stored-hash check sent
 * to the user revision commit, the stored TOON fields of the new head, and
 * conflicts or rejections reaching the editor as a failed save.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const commit = vi.fn();
/** Set to make the next commit reject (a plain rejection, outside the spy). */
let rejectWith: { message: string; failure: string } | null = null;
const projectCommit = vi.fn();
vi.mock('../../../services/embedDiffStore', () => ({
	commitEmbedContentRevision: (...args: unknown[]) => projectCommit(...args),
	isHeadPersisted: (head: { status: string }) => head.status === 'persisted' || head.status === 'adopted'
}));
vi.mock('../../../services/embedUserRevision', () => ({
	commitEmbedUserRevision: (...args: unknown[]) =>
		rejectWith !== null
			? Promise.reject(Object.assign(new Error(rejectWith.message), { failure: rejectWith.failure }))
			: commit(...args)
}));

import { deckVersionContent, saveEditedDeck, type DeckHead, type EditedDeck } from './slidesDeckVersion';

const BASE = '<deck title="Plan" aspect="16:9" template="builtin:plain">\n  <slide id="s1">\n  </slide>\n</deck>\n';
const EDITED = '<deck title="Launch plan" aspect="16:9" template="builtin:plain">\n  <slide id="s1">\n  </slide>\n</deck>\n';

const head: DeckHead = {
	embedId: 'deck-1',
	version: 3,
	markup: BASE,
	content: {
		type: 'deck', app_id: 'slides', skill_id: 'deck', slides_markup: BASE, title: 'Plan',
		slide_count: 1, aspect: '16:9', embed_ref: 'plan-AbC', status: 'finished', schema_version: 1, version_number: 3
	}
};
const edited: EditedDeck = { markup: EDITED, title: 'Launch plan', aspect: '16:9', slideCount: 1 };

async function failureOf(promise: Promise<unknown>): Promise<{ message?: unknown; failure?: unknown } | null> {
	return promise.then(() => null, (error: unknown) => error as { message?: unknown; failure?: unknown });
}

beforeEach(() => {
	commit.mockReset();
	projectCommit.mockReset();
	rejectWith = null;
});

describe('saveEditedDeck', () => {
	// contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
	it('writes nothing when the deck markup is unchanged', async () => {
		await expect(saveEditedDeck(head, { ...edited, markup: BASE }, { chatId: 'chat-1' })).resolves.toEqual({ saved: false });
		expect(commit).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation,slides.editor.save-checked-version
	it('commits the edit as the next version, checked against the stored head', async () => {
		commit.mockResolvedValue({ version: 4, cacheSynchronized: true });
		await expect(saveEditedDeck(head, edited, { chatId: 'chat-1', teamId: null })).resolves.toEqual({ saved: true, version: 4 });
		expect(commit).toHaveBeenCalledTimes(1);
		const [input] = commit.mock.calls[0];
		expect(input).toMatchObject({
			embedId: 'deck-1', chatId: 'chat-1', sourceField: 'slides_markup', originalSource: BASE, editedSource: EDITED,
			noun: 'deck', expectedHash: 'stored-head'
		});
		expect(input.current.version_number).toBe(3);
		expect(input.buildContent(EDITED, 4)).toEqual({
			...head.content, slides_markup: EDITED, title: 'Launch plan', slide_count: 1, aspect: '16:9', version_number: 4
		});
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version
	it('bases a second edit on the locally saved version, not the original embed data', async () => {
		commit.mockResolvedValue({ version: 5, cacheSynchronized: true });
		await saveEditedDeck({ ...head, version: 4, markup: EDITED }, { ...edited, markup: BASE }, { chatId: 'chat-1' });
		const [input] = commit.mock.calls[0];
		expect(input).toMatchObject({ originalSource: EDITED, editedSource: BASE });
		expect(input.current.version_number).toBe(4);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version
	it.each([
		[{ message: 'The deck changed on another device. Reload before editing.', failure: 'conflict' }],
		[{ message: 'diagram_access_denied', failure: 'rejected' }],
		[{ message: 'Deck save confirmation timed out', failure: 'transport' }]
	])('lets a refused save reach the editor as a failure (%o)', async (rejection) => {
		rejectWith = rejection;
		const failure = await failureOf(saveEditedDeck(head, edited, { chatId: 'chat-1' }));
		// Compared by fields: the test environment's Error is from another realm.
		expect(failure?.message).toBe(rejection.message);
		expect(failure?.failure).toBe(rejection.failure);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
	it('saves a Project deck through the Project revision path and reports a head the server did not take', async () => {
		projectCommit.mockResolvedValue({ version_number: 4, content_hash: 'h', head: { status: 'persisted', operation_id: 'op-1' } });
		await expect(saveEditedDeck(head, edited, { projectId: 'project-1' })).resolves.toEqual({ saved: true, version: 4 });
		expect(commit).not.toHaveBeenCalled();
		expect(projectCommit.mock.calls[0][2]).toMatchObject({ currentVersion: 3, currentContent: BASE, projectId: 'project-1' });
		projectCommit.mockResolvedValue({ version_number: 4, content_hash: 'h', head: { status: 'waiting', operation_id: 'op-2' } });
		const failure = await failureOf(saveEditedDeck(head, edited, { projectId: 'project-1' }));
		expect(String(failure?.message)).toMatch(/not saved on the server \(waiting\)/);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version
	it('refuses a deck with neither chat nor Project without sending anything', async () => {
		const failure = await failureOf(saveEditedDeck(head, edited, {}));
		expect(String(failure?.message)).toMatch(/chat or Project/);
		expect(commit).not.toHaveBeenCalled();
		expect(projectCommit).not.toHaveBeenCalled();
	});
});

describe('deckVersionContent', () => {
	// contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
	it('keeps the embed ref and ids and replaces the deck facts', () => {
		const next = deckVersionContent(head.content, { title: 'T', aspect: '4:3', slideCount: 2 }, 'M', 9);
		expect(next).toMatchObject({ embed_ref: 'plan-AbC', app_id: 'slides', type: 'deck', slides_markup: 'M', title: 'T', aspect: '4:3', slide_count: 2, version_number: 9 });
	});
});
