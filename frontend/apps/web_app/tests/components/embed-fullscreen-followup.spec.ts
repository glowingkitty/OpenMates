import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,apps.results.shared-fullscreen
  test(`fullscreen Send hands text and an image reference to its source chat at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let interpretations = 0;
    await page.route('**/v1/apps/workspace/interpret', route => {
      interpretations++;
      return route.fulfill({ status: 500, json: { detail: 'Chat followups must bypass interpretation' } });
    });
    await page.goto(`/dev/preview/embeds/ResultEmbedFollowupFixture?chrome=0&theme=light&width=${width}`);
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    const input = page.getByTestId('apps-request-textarea');
    await input.fill('Make the sky brighter');
    const send = page.getByTestId('apps-request-submit');
    await expect(send).toHaveText('Send');
    await send.focus();
    await expect(send).toBeFocused();
    await send.click();
    await expect(page.getByTestId('followup-destination')).toHaveText('e2e-fullscreen-followup-source');
    const document = page.getByTestId('followup-document');
    await expect(document).toContainText('Make the sky brighter');
    await expect(document).toContainText('"embed_id": "11111111-1111-4111-8111-11111111f011"');
    await expect(document).toContainText('"reference_only": true');
    await expect(document).not.toContainText('Result context');
    expect(interpretations).toBe(0);
  });
}
