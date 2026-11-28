// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video of both browsers and the named screenshots cover each state)
/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Live collaboration under stress between two real Team members: removal
 * during a session, offline reconnect, and a version restore while the other
 * person types (web, isolated CI stack, `live_collaboration` flag on).
 *
 * Specification: specifications/features/live-collaboration/specification.yml
 * (live-collab.access.roles, live-collab.keys.rotation-on-removal,
 * live-collab.offline.merge-on-reconnect, live-collab.versions.named-snapshots).
 * Run: ci_coordinator.py submit --mode e2e --spec live-collab-conflicts.spec.ts
 */

import type { Browser, Page, Response } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const { test, expect } = require('./helpers/cookie-audit');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const live = require('./helpers/live-collab');

test.afterEach(async () => {
	await live.attachLiveDiagnostics();
});

test.describe.configure({ mode: 'serial' });

async function begin(page: Page, browser: Browser) {
	const owner = getTestAccount(1);
	const member = getTestAccount(2);
	test.skip(!owner.email || !member.email || owner.email === member.email, 'Two isolated account identities required.');
	await skipIfFeaturesDisabled(test, page, ['platform:teams', 'platform:projects']);
	await page.setViewportSize({ width: 1440, height: 1000 });
	await live.enableLiveFlag(page.context());
	await live.loginToTestAccount(page, undefined, undefined, { credentials: owner });
	const setup: import('./helpers/live-collab').TeamSetup = await live.openLivePair(page, browser, owner, member, 'document', 'Recipe collection', 'Soup recipes');
	const a = page.getByTestId('project-embed-viewer').getByTestId('docs-editor-content');
	const b = setup.member.getByTestId('project-embed-viewer').getByTestId('docs-editor-content');
	await expect(a).toBeVisible({ timeout: 30_000 });
	await expect(b).toBeVisible({ timeout: 30_000 });
	await a.click();
	await page.keyboard.type('Pumpkin soup needs ginger');
	await expect.poll(() => live.editorText(b), { timeout: 15_000 }).toContain('Pumpkin soup needs ginger');
	return { setup, a, b };
}

// Keep the owner's editor open while changing membership.
async function removeMember(owner: Page, teamId: string, teamName: string) {
	const settings = await owner.context().newPage();
	try {
		await settings.goto('/');
		await live.enterTeam(settings, teamId, teamName);
		await settings.goto(getE2EDebugUrl(`/#settings/teams/${teamId}`));
		await settings.getByTestId('team-members-open').click();
		await expect(settings.getByTestId('team-member-row')).toHaveCount(2, { timeout: 30_000 });
		await settings.getByTestId('team-member-row').last().click();
		await settings.getByRole('checkbox', { name: /lose access/i }).click();
		const removed = settings.waitForResponse((response: Response) =>
			response.request().method() === 'POST' &&
			/\/members\/[^/]+\/remove$/.test(new URL(response.url()).pathname) && response.ok()
		);
		await settings.getByTestId('team-member-remove').click();
		await removed;
	} finally {
		await settings.close();
	}
}

async function expectSealedOfflineEdit(member: Page, note: string, requirePrivateCopy = false) {
	await expect.poll(() => member.evaluate(({ text, requirePrivateCopy }) => new Promise<boolean>((resolve, reject) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => reject(open.error);
		open.onsuccess = () => {
			const db = open.result;
			const tx = db.transaction('live_item_outbox', 'readonly');
			const request = tx.objectStore('live_item_outbox').getAll();
			tx.onabort = () => { db.close(); reject(tx.error); };
			tx.oncomplete = () => {
				db.close();
				const records = request.result;
				const sealed = records.length > 0 && records.every((record: unknown) =>
					typeof record === 'string' && record.startsWith('[') && !record.includes(text.trim()));
				const hasPrivateCopy = (record: string) => {
					const value = JSON.parse(record);
					return value[0] === 'openmates-live-recovery-v1' && Array.isArray(value[2]) &&
						value[2].some((copy: { sealed?: unknown }) => typeof copy.sealed === 'string' && copy.sealed.length > 0);
				};
				resolve(sealed && (!requirePrivateCopy || records.some(hasPrivateCopy)));
			};
		};
	}), { text: note, requirePrivateCopy }), { timeout: 15_000 }).toBe(true);
}

// contract-test: direct surface=gui.web assertions=live-collab.access.roles,live-collab.keys.rotation-on-removal
test('a member removed during a session loses access and their later typing never reaches the owner', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const rotatedWrites = new Set<string>();
	const acknowledgedWrites = new Set<string>();
	page.on('websocket', (socket) => {
		socket.on('framesent', ({ payload }) => {
			const frame = payload.toString();
			if (!frame.includes('"live_item_update"')) return;
			const { payload: update } = JSON.parse(frame);
			if (update.epoch === 2) rotatedWrites.add(update.client_msg_id);
		});
		socket.on('framereceived', ({ payload }) => {
			const frame = payload.toString();
			if (!frame.includes('"live_item_update_ack"')) return;
			const { payload: ack } = JSON.parse(frame);
			acknowledgedWrites.add(ack.client_msg_id);
		});
	});
	const { setup, a, b } = await begin(page, browser);
	try {
		const timeline = page.getByTestId('embed-version-timeline');
		await page.getByTestId('docs-edit-button').click();
		await expect(timeline.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });
		await page.getByTestId('docs-edit-button').click();
		await expect(a).toBeVisible({ timeout: 30_000 });
		await live.shot(setup.member, 'member-before-removal');
		await removeMember(page, setup.teamId, setup.teamName);

		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'access_revoked', { timeout: 60_000 });
		await live.shot(setup.member, 'member-access-revoked');

		const ownerBefore = await live.editorText(a);
		await expect(b).toHaveAttribute('contenteditable', 'false');
		await b.focus();
		await setup.member.keyboard.type(' removed-member-text');
		await expect(b).not.toContainText('removed-member-text');
		expect(await live.editorText(a)).toBe(ownerBefore);
		expect(await live.editorText(a)).not.toContain('removed-member-text');
		// The owner keeps editing normally.
		const stored = page.waitForResponse((response) => {
			const request = response.request();
			return request.method() === 'POST' && response.ok() &&
				new URL(response.url()).pathname.endsWith('/user-revisions') &&
				request.postDataJSON()?.head?.encrypted_content?.startsWith('OMRV1.2.');
		}, { timeout: 45_000 });
		await a.click();
		await page.keyboard.press('Control+End');
		await page.keyboard.type(' and garlic');
		await expect.poll(() => live.editorText(a), { timeout: 15_000 }).toContain('and garlic');
		await expect.poll(
			() => [...rotatedWrites].some(id => acknowledgedWrites.has(id)),
			{ timeout: 30_000 },
		).toBe(true);
		await live.shot(page, 'owner-after-removal');
		await page.getByTestId('docs-edit-button').click();
		expect((await (await stored).json()).status).toBe('committed');

		// A fresh page must decrypt the persisted head without using the open replica.
		const reopened = await page.context().newPage();
		try {
			await reopened.goto('/');
			await live.enterTeam(reopened, setup.teamId, setup.teamName);
			await live.openProjectFile(reopened, setup.projectId, 'Soup recipes');
			const viewer = reopened.getByRole('region', { name: 'Document viewer' });
			await expect(viewer.getByText('Pumpkin soup needs ginger and garlic')).toBeInViewport();
			await expect(viewer).not.toContainText('removed-member-text');
			await live.shot(reopened, 'owner-reopened-post-removal-revision');
			const reopenedTimeline = reopened.getByTestId('embed-version-timeline');
			const historicalText = viewer.getByText('Pumpkin soup needs ginger', { exact: true });
			await reopenedTimeline.getByTestId('version-dot-2').click();
			await historicalText.scrollIntoViewIfNeeded();
			await expect(historicalText).toBeInViewport();
			const restored = reopened.waitForResponse((response) => {
				const request = response.request();
				if (request.method() !== 'POST' || !response.ok() ||
					!new URL(response.url()).pathname.endsWith('/user-revisions')) return false;
				const body = request.postDataJSON();
				return body?.restored_from === 2 && body?.head?.encrypted_content?.startsWith('OMRV1.2.');
			}, { timeout: 45_000 });
			const restoreButton = reopened.getByTestId('restore-version-btn');
			await restoreButton.click();
			await restoreButton.click();
			expect((await (await restored).json()).status).toBe('committed');
			await expect(reopenedTimeline.getByTestId('version-dot-4')).toBeVisible();
			await historicalText.scrollIntoViewIfNeeded();
			await expect(historicalText).toBeInViewport();
			await live.shot(reopened, 'owner-restored-pre-removal-revision');
		} finally {
			await reopened.close();
		}
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.offline.merge-on-reconnect,live-collab.sync.concurrent-convergence
test('a member who goes offline and comes back merges their edits with the owner edits', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const { setup, a, b } = await begin(page, browser);
	try {
		await setup.memberContext.setOffline(true);
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'offline', { timeout: 30_000 });
		await live.shot(setup.member, 'member-offline');

		await b.click();
		await setup.member.keyboard.press('Control+Home');
		await setup.member.keyboard.type('Offline note. ');
		await a.click();
		await page.keyboard.press('Control+End');
		await page.keyboard.type(' Online note.');
		await expect.poll(() => live.editorText(a), { timeout: 15_000 }).toContain('Online note.');
		expect(await live.editorText(b)).not.toContain('Online note.');
		await live.shot(page, 'owner-typed-while-member-offline');

		await setup.memberContext.setOffline(false);
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 60_000 });
		await expect.poll(async () => (await live.editorText(a)) === (await live.editorText(b)), { timeout: 30_000 }).toBe(true);
		expect(await live.editorText(a)).toContain('Offline note.');
		expect(await live.editorText(a)).toContain('Online note.');
		expect(await live.editorText(a)).toContain('Pumpkin soup needs ginger');
		await live.shot(page, 'owner-merged');
		await live.shot(setup.member, 'member-merged-saved');
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.offline.merge-on-reconnect
test('an offline member can close the editor and recover their queued edit in a new tab', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const { setup, a, b } = await begin(page, browser);
	const note = 'Keep this after reopening. ';
	try {
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		await setup.memberContext.setOffline(true);
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'offline', { timeout: 30_000 });
		await b.click();
		await setup.member.keyboard.press('Control+Home');
		await setup.member.keyboard.insertText(note);
		await expect(b).toContainText(note.trim());
		await expectSealedOfflineEdit(setup.member, note);
		expect(await live.editorText(a)).not.toContain(note.trim());
		await live.shot(setup.member, 'offline-queued-before-close');
		await setup.member.close();

		await a.click();
		await page.keyboard.press('Control+End');
		await page.keyboard.insertText(' Owner edited while the other tab was closed.');
		await setup.memberContext.setOffline(false);
		const reopened = await setup.memberContext.newPage();
		live.captureLiveDiagnostics(reopened, test.info(), 'member-reopened');
		await reopened.goto('/');
		await live.enterTeam(reopened, setup.teamId, setup.teamName);
		await live.openProjectFile(reopened, setup.projectId, 'Soup recipes');
		await live.startLiveEditing(reopened, 'document');
		const restored = reopened.getByTestId('project-embed-viewer').getByTestId('docs-editor-content');
		await expect(restored).toContainText(note.trim(), { timeout: 45_000 });
		await expect(a).toContainText(note.trim(), { timeout: 45_000 });
		await expect(restored).toContainText('Owner edited while the other tab was closed.');
		await expect(reopened.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		await live.shot(reopened, 'reopened-offline-edit-merged');
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.offline.merge-on-reconnect,live-collab.access.roles
test('an offline member removed from the Team can download their unsent edits', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const { setup, a, b } = await begin(page, browser);
	const offlineText = 'Add cinnamon after serving.';
	const sentAfterReconnect: string[] = [];
	try {
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		await setup.memberContext.setOffline(true);
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'offline', { timeout: 30_000 });
		await b.click();
		await setup.member.keyboard.press('Control+End');
		await setup.member.keyboard.insertText(` ${offlineText}`);
		await expect(b).toContainText(offlineText);
		await removeMember(page, setup.teamId, setup.teamName);

		setup.member.on('websocket', (socket: import('@playwright/test').WebSocket) => {
			socket.on('framesent', ({ payload }) => {
				if (payload.toString().includes('"live_item_update"')) sentAfterReconnect.push(payload.toString());
			});
		});
		await setup.memberContext.setOffline(false);
		const recover = setup.member.getByRole('button', { name: 'Download private copy', exact: true });
		await expect(recover).toBeVisible({ timeout: 60_000 });
		await live.shot(setup.member, 'removed-member-can-download-private-copy');
		const downloadEvent = setup.member.waitForEvent('download');
		await recover.click();
		const download = await downloadEvent;
		expect(download.suggestedFilename()).toBe('Recovered document.txt');
		const downloadedPath = await download.path();
		expect(await readFile(downloadedPath, 'utf8')).toContain(offlineText);
		await expect(recover).toHaveCount(0);
		expect(sentAfterReconnect).toHaveLength(0);
		expect(await live.editorText(a)).not.toContain(offlineText);
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.versions.named-snapshots,live-collab.sync.concurrent-convergence
test('the owner restores an older version while the member types and both keep the restored text plus the new text', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const { setup, a, b } = await begin(page, browser);
	try {
		// Version 2: leaving edit mode writes the version of the text typed so far (version 1 is
		// the empty file); then edit again.
		const timeline = page.getByTestId('embed-version-timeline');
		await page.getByTestId('docs-edit-button').click();
		await expect(timeline.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });
		await page.getByTestId('docs-edit-button').click();
		await expect(a).toBeVisible({ timeout: 30_000 });
		await a.click();
		await page.keyboard.press('Control+End');
		await page.keyboard.type(' with too much salt');
		await expect.poll(() => live.editorText(b), { timeout: 15_000 }).toContain('with too much salt');
		await page.getByTestId('docs-edit-button').click();

		await expect(timeline).toBeVisible({ timeout: 30_000 });
		// The read view shows the text just typed, not the stored first version.
		await expect(page.getByTestId('project-embed-viewer')).toContainText('with too much salt', { timeout: 30_000 });
		await expect(timeline.getByTestId('version-dot-3')).toBeVisible({ timeout: 30_000 });
		await live.shot(page, 'owner-version-timeline');
		await timeline.getByTestId('version-dot-2').click();
		await expect(page.getByTestId('restore-version-btn')).toBeVisible();

		// The member types while the owner restores.
		await b.click();
		await setup.member.keyboard.press('Control+End');
		await setup.member.keyboard.type(' plus lemon');
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved');
		await page.getByTestId('restore-version-btn').click();
		await page.getByTestId('restore-version-btn').click();
		await expect.poll(() => live.editorText(b), { timeout: 30_000 }).not.toContain('too much salt');
		expect(await live.editorText(b)).toContain('Pumpkin soup needs ginger');
		expect(await live.editorText(b)).toContain('plus lemon');
		const restoredText = page.getByRole('region', { name: 'Document viewer' }).getByText('plus lemon');
		await restoredText.scrollIntoViewIfNeeded();
		await expect(restoredText).toBeInViewport();
		await live.shot(page, 'owner-after-restore');
		await live.shot(setup.member, 'member-after-restore');
		await expect(timeline.getByTestId('version-dot-4')).toBeVisible({ timeout: 30_000 });
		await expect(timeline.locator('[data-testid^="version-dot-"]')).toHaveCount(4);
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.offline.merge-on-reconnect,live-collab.access.roles
test('an offline member can recover a private copy after closing the editor and losing Team access', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const { setup, a, b } = await begin(page, browser);
	const offlineText = 'Save the roasted seeds for serving.';
	try {
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		await setup.memberContext.setOffline(true);
		await expect(setup.member.getByTestId('live-header-status')).toHaveAttribute('data-status', 'offline', { timeout: 30_000 });
		await b.click();
		await setup.member.keyboard.press('Control+End');
		await setup.member.keyboard.insertText(` ${offlineText}`);
		await expect(b).toContainText(offlineText);
		await expectSealedOfflineEdit(setup.member, offlineText, true);
		await setup.member.close();
		await removeMember(page, setup.teamId, setup.teamName);

		await setup.memberContext.setOffline(false);
		const reopened = await setup.memberContext.newPage();
		live.captureLiveDiagnostics(reopened, test.info(), 'removed-member-reopened');
		const sentUpdates: string[] = [];
		reopened.on('websocket', (socket) => {
			socket.on('framesent', ({ payload }) => {
				const frame = payload.toString();
				if (frame.includes('"live_item_update"')) sentUpdates.push(frame);
			});
		});
		await reopened.goto('/');
		const recover = reopened.getByRole('button', { name: 'Download private copy', exact: true });
		await expect(recover).toBeVisible({ timeout: 60_000 });
		await live.shot(reopened, 'removed-member-private-copy-after-reopening');
		const pendingDownload = reopened.waitForEvent('download');
		await recover.click();
		const download = await pendingDownload;
		const recovered = await readFile(await download.path(), 'utf8');
		expect(recovered).toContain('Pumpkin soup needs ginger');
		expect(recovered).toContain(offlineText);
		await expect(recover).toHaveCount(0);
		expect(sentUpdates).toHaveLength(0);
		expect(await live.editorText(a)).not.toContain(offlineText);
	} finally {
		await live.cleanupTeam(page, setup);
	}
});
