// playwright-account: not_required reason=public_logged_out_example_admission
/* eslint-disable @typescript-eslint/no-require-imports -- The browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';
const { test } = require('./helpers/cookie-audit');
import { dashboardSidebarSvgIconsChat } from '../../../packages/ui/src/demo_chats/data/example_chats/dashboard-sidebar-svg-icons';
import { communityGardenWelcomeMelodyChat } from '../../../packages/ui/src/demo_chats/data/example_chats/community-garden-welcome-melody';
import { housingPolicyDinnerDiscussionChat } from '../../../packages/ui/src/demo_chats/data/example_chats/housing-policy-dinner-discussion';

const reviewed = [
  { appId: 'design', chat: dashboardSidebarSvgIconsChat },
  { appId: 'music', chat: communityGardenWelcomeMelodyChat },
  { appId: 'politics', chat: housingPolicyDinnerDiscussionChat }
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
