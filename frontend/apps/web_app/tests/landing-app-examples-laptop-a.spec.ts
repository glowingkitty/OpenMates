// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { admitLandingExample, landingAdmissionCases } from './landing-app-example-admission';
const { test } = require('./helpers/cookie-audit');

for (const { appId, chat } of landingAdmissionCases(0)) {
  test(`${appId} landing example admits its complete real chat on laptop`, async ({ page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo) => {
    test.setTimeout(90_000);
    await admitLandingExample(page, request, testInfo, appId, chat, 'laptop');
  });
}
