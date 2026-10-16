// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering,app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { communityGardenVolunteerChimeChat } from '../../../packages/ui/src/demo_chats/data/example_chats/community-garden-volunteer-chime';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';

const { test, expect } = require('./helpers/cookie-audit');
const reviewed = [
  { appId: 'audio', chat: communityGardenVolunteerChimeChat },
];

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  for (const { appId, chat } of reviewed) {
    // contract-test: direct surface=gui.web assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering,app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
    test(`${appId} reviewed replacement renders its real results on ${viewport}`, async (
      { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
    ) => {
      test.setTimeout(180_000);
      await admitLandingExample(page, request, testInfo, appId, chat, viewport);
      // A valid result preview must not conceal another broken Markdown image
      // in the same answer. Inspect visible pixels, including legacy image refs.
      await expect.poll(() => page.getByTestId('message-assistant').locator('img').evaluateAll(
        (images: HTMLImageElement[]) => images.filter(image => {
          const rect = image.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight;
        }).every(image => image.complete && image.naturalWidth > 0)
      ), { message: `${chat.slug}: every visible assistant image has real pixels` }).toBe(true);
    });
  }
}
