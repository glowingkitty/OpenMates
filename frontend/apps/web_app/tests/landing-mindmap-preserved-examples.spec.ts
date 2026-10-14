// playwright-account: not_required reason=public_logged_out_example_admission
/* eslint-disable @typescript-eslint/no-require-imports -- The browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';
const { test } = require('./helpers/cookie-audit');
import { berlinEnglishSpeakingGpAppointmentsChat } from '../../../packages/ui/src/demo_chats/data/example_chats/berlin-english-speaking-gp-appointments';
import { booksAfterLeftHandOfDarknessChat } from '../../../packages/ui/src/demo_chats/data/example_chats/books-after-left-hand-of-darkness';
import { buckConverters24v5vChat } from '../../../packages/ui/src/demo_chats/data/example_chats/buck-converters-24v-5v';
import { printableBenchyPhoneStandModelsChat } from '../../../packages/ui/src/demo_chats/data/example_chats/printable-benchy-phone-stand-models';

const reviewed = [
  { appId: 'health', chat: berlinEnglishSpeakingGpAppointmentsChat },
  { appId: 'books', chat: booksAfterLeftHandOfDarknessChat },
  { appId: 'electronics', chat: buckConverters24v5vChat },
  { appId: 'models3d', chat: printableBenchyPhoneStandModelsChat }
];

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  for (const { appId, chat } of reviewed) {
    // contract-test: direct surface=gui.web assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering,public-example-chats.catalog.discoverable,marketing-landing.interactive-rail,marketing-landing.hero-app-rail
    test(`${appId} mindmap example verifies header, transcript and artifacts on ${viewport}`, async (
      { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
    ) => {
      test.setTimeout(180_000);
      await admitLandingExample(page, request, testInfo, appId, chat, viewport);
    });
  }
}
