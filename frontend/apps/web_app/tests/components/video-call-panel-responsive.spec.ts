// playwright-account: not_required reason=isolated_component_preview
/**
 * Responsive call-panel coverage retained for future runs.
 * Execution is waived for the initial experiment delivery at the user's request.
 * All media is synthetic; this fixture never calls a provider.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant: string, width: number) =>
  `/dev/preview/videocall/VideoCallPanel?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), variant })}`;

test.use({ launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] } });

test.describe('Responsive video call experiment panel', () => {
  // contract-test: direct surface=gui.web assertions=video-call.experiment.responsive,video-call.experiment.user-stop
  test('keeps stop, hangup and transcript controls available on a narrow screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('visuals', 390));
    await waitForComponentPreview(page);
    const panel = page.getByTestId('video-call-panel');
    const stageBounds = await page.getByTestId('video-call-stage').boundingBox();
    expect(stageBounds).not.toBeNull();
    expect(stageBounds!.y).toBe(0);
    expect(stageBounds!.height).toBeGreaterThanOrEqual(844);
    const viewportWidth = page.viewportSize()!.width;
    for (const testId of ['call-top-bar', 'call-heading', 'call-timer', 'call-exit']) {
      const bounds = await page.getByTestId(testId).boundingBox();
      expect(bounds, `${testId} should have a rendered box`).not.toBeNull();
      expect(bounds!.x, `${testId} should start inside the phone viewport`).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width, `${testId} should end inside the phone viewport`).toBeLessThanOrEqual(viewportWidth);
    }
    const topBarBounds = await page.getByTestId('call-top-bar').boundingBox();
    expect(topBarBounds!.x, 'the full-page header should align with phone padding').toBeLessThanOrEqual(20);
    await expect(page.getByTestId('call-timer')).toContainText('1:22');
    await expect(page.getByTestId('call-stop-video')).toBeVisible();
    await expect(page.getByTestId('call-hangup')).toBeVisible();
    await expect(page.getByTestId('call-chat-toggle')).toBeVisible();
    await page.getByTestId('call-chat-toggle').click();
    await expect(page.getByTestId('call-context-panel')).toBeVisible();
    await expect(page.getByTestId('call-drawer-hangup')).toBeVisible();
    await expect(page.getByTestId('call-transcript')).toContainText('Charged particles');
    await expect.poll(() => panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.getByText('Close transcript').click();
    await expect(page.getByTestId('call-context-panel')).toBeHidden();
    await expect(page.getByTestId('call-hangup')).toBeVisible();
  });
});
