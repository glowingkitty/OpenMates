/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Web E2E coverage for Diagrams/Mermaid embeds.
 *
 * Uses the deterministic dev embed showcase instead of AI generation so the
 * renderer contract is stable: preview crop, source fallback, and fullscreen
 * pan/zoom/source controls must all render on the deployed dev app.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');

async function waitForComponentPreview(page: any, componentPath: string, componentName: string) {
	const response = await page.goto(`/dev/preview/${componentPath}`, { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('breadcrumb-name')).toContainText(componentName);
	await expect(page.getByTestId('preview-status-bar')).toContainText('preview.ts loaded');
	await expect(page.getByTestId('render-error')).toHaveCount(0);
}

test.describe('Diagrams Mermaid embeds', () => {
	test('preview and fullscreen render Mermaid controls and source fallback', async ({ page }: { page: any }) => {
		await waitForComponentPreview(
			page,
			'embeds/diagrams/MermaidDiagramEmbedPreview',
			'MermaidDiagramEmbedPreview'
		);

		const preview = page.getByTestId('mermaid-diagram-preview').first();
		await expect(preview).toBeVisible({ timeout: 20_000 });
		await expect(async () => {
			const renderedCount = await preview.getByTestId('mermaid-rendered-preview').count();
			const fallbackCount = await preview.getByTestId('mermaid-source-fallback').count();
			expect(renderedCount + fallbackCount).toBeGreaterThan(0);
		}).toPass({ timeout: 20_000 });
		await expect(preview).toContainText('Email Signup Sequence');
		await expect(preview).toContainText('sequenceDiagram');

		await waitForComponentPreview(
			page,
			'embeds/diagrams/MermaidDiagramEmbedFullscreen',
			'MermaidDiagramEmbedFullscreen'
		);

		const fullscreen = page;
		await expect(fullscreen.getByTestId('mermaid-diagram-fullscreen')).toBeVisible({ timeout: 20_000 });
		await expect(fullscreen.getByTestId('mermaid-diagram-controls')).toBeVisible();
		await expect(fullscreen.getByTestId('mermaid-zoom-in')).toBeVisible();
		await expect(fullscreen.getByTestId('mermaid-zoom-out')).toBeVisible();
		await expect(fullscreen.getByTestId('mermaid-fit')).toBeVisible();

		const sourcePanel = fullscreen.getByTestId('mermaid-source-panel');
		if (!(await sourcePanel.isVisible().catch(() => false))) {
			await fullscreen.getByTestId('mermaid-toggle-source').click();
		}
		await expect(sourcePanel).toBeVisible();
		await expect(sourcePanel).toContainText('participant User');
	});
});
