import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const BASE = '/dev/preview/ChatOrchestrationEventNotice?chrome=0&theme=light&width=480';
test.use({ viewport: { width: 800, height: 400 }, trace: 'retain-on-failure' });

const CASES: [string, RegExp][] = [
  ['', /Started chat "Kitchen tile quotes"/],
  ['report', /Report from "Kitchen tile quotes"/],
  ['sent', /Sent to "Kitchen tile quotes"/],
  ['reported', /Reported to "Kitchen tile quotes"/],
  ['finished', /"Kitchen tile quotes" finished/],
  ['waiting_for_user', /"Kitchen tile quotes" is waiting for you/],
  ['user_wrote', /You wrote in "Kitchen tile quotes"/],
];

for (const [variant, line] of CASES) {
  // contract-test: direct surface=gui.web assertions=chat-orchestration.events.creator-system-events
  test(`shows the ${variant || 'started'} event as one compact clickable line`, async ({ page }, testInfo) => {
    await page.goto(variant ? `${BASE}&variant=${variant}` : BASE);
    await waitForComponentPreview(page);
    const notice = page.getByTestId('chat-orchestration-event');
    await expect(notice).toBeVisible();
    await expect(notice).toHaveText(line);
    await expect(notice.locator('time')).toBeVisible();
    if (variant === 'report') {
      await expect(page.getByTestId('chat-orchestration-report')).toContainText(/porcelain/);
    }
    if (variant === 'sent') {
      await expect(page.getByTestId('chat-orchestration-report')).toContainText(/compare porcelain/);
    }
    if (variant === 'reported') {
      await expect(page.getByTestId('chat-orchestration-report')).toContainText(/best fit/);
    }
    // Regression: the global button style (fixed 41px height) clipped the text below the line.
    expect(await notice.evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
    await testInfo.attach(`${variant || 'started'}-event`, {
      body: await notice.screenshot(), contentType: 'image/png',
    });
  });
}
