// playwright-account: not_required reason=public_logged_out_example_admission
/* eslint-disable @typescript-eslint/no-require-imports -- The browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { admitLandingExample } from './landing-app-example-admission';
import { findBrandNameAndDomainChat } from '../../../packages/ui/src/demo_chats/data/example_chats/find-brand-name-and-domain';
const { test } = require('./helpers/cookie-audit');

// contract-test: direct surface=gui.web assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering,public-example-chats.catalog.discoverable,marketing-landing.interactive-rail,marketing-landing.hero-app-rail,chat-processing-feedback.completed-processing-summary,public-example-chats.surface.semantic-parity
test('web search example verifies header, complete transcript and successful results on phone', async (
  { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
) => {
  test.setTimeout(240_000);
  await admitLandingExample(page, request, testInfo, 'web', findBrandNameAndDomainChat, 'phone');
});
