// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
//
// One Edit button for every editable embed type: the round pencil at the start of
// the fullscreen header turns into a round check mark while editing, and the check
// saves and leaves edit mode. Saving unchanged content just leaves edit mode, so
// no preview save stub is needed here; real saves are proven by the route E2E specs
// (projects-create-edit-files, chat-embed-header-edit, slides-manual-edit, diagram-html-editing).
import type { Locator, Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

const preview = (component: string, variant: string, width = 1280) =>
	`/dev/preview/embeds/${component}?${new URLSearchParams({ variant, chrome: '0', theme: 'light', background: '#dbeafe', width: String(width) })}`;

interface Case {
	name: string;
	component: string;
	variant: string;
	testId: string;
	/** Waits until the editor is ready, so the check is enabled. */
	ready?: (page: Page) => Promise<void>;
	/** The editor surface that exists only in edit mode. */
	editor: (page: Page) => Locator;
}

const cases: Case[] = [
	{ name: 'document in a Project', component: 'docs/DocsEmbedFullscreen', variant: 'editableInProject', testId: 'docs-edit-button', editor: (page) => page.getByTestId('docs-editor') },
	{ name: 'document in a chat', component: 'docs/DocsEmbedFullscreen', variant: 'editableInChat', testId: 'docs-edit-button', editor: (page) => page.getByTestId('docs-editor') },
	{ name: 'code file in a Project', component: 'code/CodeEmbedFullscreen', variant: 'editableInProject', testId: 'code-edit-button', editor: (page) => page.getByTestId('code-editor') },
	{ name: 'sheet', component: 'sheets/SheetEmbedFullscreen', variant: 'editableFormulas', testId: 'sheet-edit-toggle', editor: (page) => page.locator('[data-testid="sheet-fullscreen"][data-edit-mode="true"]') },
	{
		name: 'slide deck', component: 'slides/SlidesDeckEmbedFullscreen', variant: 'editable', testId: 'slides-edit',
		ready: async (page) => { await expect(page.getByTestId('slides-editor')).toHaveAttribute('data-status', 'ready', { timeout: 60_000 }); },
		editor: (page) => page.getByTestId('slides-editor')
	},
	{
		name: 'diagram', component: 'diagrams/DiagramHtmlEmbedFullscreen', variant: 'editable', testId: 'embed-edit-button',
		ready: async (page) => { await expect(page.getByTestId('diagram-html-canvas')).toHaveAttribute('data-editor-ready', 'true', { timeout: 30_000 }); },
		editor: (page) => page.locator('[data-testid="diagram-html-canvas"][data-editing="true"]')
	}
];

async function attachHeader(page: Page, name: string): Promise<void> {
	const header = page.getByTestId('embed-top-bar').first();
	await test.info().attach(`${name}-header`, { body: await header.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
	await test.info().attach(`${name}-page`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
}

async function expectRoundLeading(page: Page, button: Locator): Promise<void> {
	const pill = (await button.locator('xpath=..').boundingBox())!;
	expect(Math.abs(pill.width - pill.height), 'the Edit button is round').toBeLessThanOrEqual(1);
	// Leading header action: it sits left of Share (or the More menu on narrow headers).
	const topBar = page.getByTestId('embed-top-bar').first();
	const share = topBar.getByTestId('embed-share-button');
	const next = (await share.isVisible()) ? share : topBar.getByRole('button', { name: /more/i }).last();
	expect(pill.x, 'Edit comes before Share').toBeLessThan((await next.boundingBox())!.x);
}

for (const width of [1280, 390]) {
	for (const item of cases) {
		// contract-test: direct surface=gui.web assertions=embed-user-edits.header.edit-save-button
		test(`${item.name}: header pencil becomes a round check that saves and leaves edit mode at ${width}px`, async ({ page }) => {
			await page.setViewportSize({ width, height: 900 });
			await page.goto(preview(item.component, item.variant, width));
			await waitForComponentPreview(page);
			await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
			const slug = `${item.name.replace(/\s+/g, '-')}-${width}`;

			const button = page.getByTestId('embed-top-bar').first().getByTestId(item.testId);
			await expect(button).toBeVisible({ timeout: 20_000 });
			await expect(button).toHaveAttribute('data-edit-state', 'edit');
			await expect(button.getByTestId('embed-edit-icon')).toBeVisible();
			await expect(item.editor(page)).toHaveCount(0);
			await expectRoundLeading(page, button);
			await attachHeader(page, `${slug}-pencil`);

			await button.click();
			await item.ready?.(page);
			await expect(button).toHaveAttribute('data-edit-state', 'save');
			await expect(button.getByTestId('embed-edit-save-icon')).toBeVisible();
			await expect(button).toBeEnabled();
			await expect(button).toHaveAttribute('aria-label', /save/i);
			await expectRoundLeading(page, button);
			await attachHeader(page, `${slug}-check`);

			// Unchanged content: the check leaves edit mode without writing a version.
			await button.click();
			await expect(button).toHaveAttribute('data-edit-state', 'edit', { timeout: 20_000 });
			await expect(button.getByTestId('embed-edit-icon')).toBeVisible();
			await expect(item.editor(page)).toHaveCount(0);
		});
	}
}
