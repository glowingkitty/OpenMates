/**
 * Mindmap normal-view source visibility regression.
 * Uses public component data without a provider, upload or account dependency.
 * Supports public-example safe rendering and the TASK-18 no-JSON acceptance.
 * Invalid-source recovery and canonical download remain separately asserted.
 * See docs/architecture/mindmap-fullscreen-design-proposal.md.
 */
import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/mindmaps/MindMapEmbedFullscreen?chrome=0';
const SOURCE_MARKER = '"openmatesType"';
const MAX_ZOOM_CONTROL_HEIGHT = 64;

// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
test('reduced motion closes the shared fullscreen without an animated waiting period', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(PREVIEW);
  const overlay = page.getByTestId('embed-fullscreen-overlay');
  await expect(overlay.getByTestId('mindmap-fullscreen-canvas')).toBeVisible();
  // Evaluate at the next painted frame, rather than letting assertion retries
  // conceal a fixed close delay. The preview intentionally keeps its root mounted.
  const visibility = await page.getByTestId('embed-minimize').evaluate(async (button: HTMLElement) => {
    button.click();
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    return getComputedStyle(document.querySelector('[data-testid="embed-fullscreen-overlay"]')!).visibility;
  });
  expect(visibility).toBe('hidden');
});

// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('normal fullscreen renders the map without exposing source JSON', async ({ page }) => {
  await page.goto(PREVIEW);
  const overlay = page.getByTestId('embed-fullscreen-overlay');
  await expect(overlay.getByTestId('mindmap-fullscreen-canvas')).toBeVisible();
  await expect(overlay.getByTestId('mindmap-node').first()).toContainText('Customer Interviews');
  await expect(overlay).not.toContainText(SOURCE_MARKER);
  const zoomBarHeight = await overlay.getByTestId('mindmap-zoom-reset').evaluate(
    (button: HTMLElement) => button.parentElement!.getBoundingClientRect().height
  );
  expect(zoomBarHeight).toBeLessThanOrEqual(MAX_ZOOM_CONTROL_HEIGHT);
  // Narrow fullscreen headers place Download inside the responsive More menu.
  // Open the same visible control a phone user needs before checking the export.
  const moreActions = overlay.getByRole('button', { name: 'More', exact: true });
  if (await moreActions.isVisible()) {
    await moreActions.click();
  }
  const download = overlay.getByTestId('embed-download-button');
  await expect(download).toBeVisible();
  await expect(download).toHaveAttribute('download', /launch-plan.*\.ommindmap$/);
  const exported = await download.evaluate(async (element: HTMLAnchorElement) =>
    (await fetch(element.href)).json());
  expect(exported).toMatchObject({ openmatesType: 'mindmap', title: 'Launch Plan' });
});

// Existing mindmap Plan S-4 / AC-4 preserves invalid-source recovery.
// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('invalid fullscreen retains a visible error and copyable original source', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=invalidSource`);
  const overlay = page.getByTestId('embed-fullscreen-overlay');
  await expect(overlay).toContainText('Invalid mind map JSON');
  await expect(overlay).toContainText('This is not a valid mindmap document');
  await expect(overlay.getByTestId('mindmap-fullscreen-canvas')).toHaveCount(0);
});
