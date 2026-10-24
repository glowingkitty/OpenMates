// playwright-account: not_required reason=public_logged_out_example_admission
/* eslint-disable @typescript-eslint/no-require-imports -- The shared admission helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { furnishedApartmentsBerlinChat } from '../../../packages/ui/src/demo_chats/data/example_chats/furnished-apartments-berlin';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';
const { test, expect } = require('./helpers/cookie-audit');

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,home-search.images.complete-gallery,home-search.web.map-and-filter,home-search.listings.rich-provider-evidence,app-skills.history.renderable
  test(`home replacement admits its real apartment search and rich results on ${viewport}`, async (
    { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
  ) => {
    test.setTimeout(150_000);
    expect(furnishedApartmentsBerlinChat.metadata.app_skill_examples).toContain('home.search');
    expect(furnishedApartmentsBerlinChat.follow_up_suggestions.length).toBeGreaterThan(0);
    await admitLandingExample(page, request, testInfo, 'home', furnishedApartmentsBerlinChat, viewport);
  });
}
