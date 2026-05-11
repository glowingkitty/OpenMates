/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * E2E coverage for GitHub repository embeds.
 *
 * Verifies that a pasted GitHub repository URL is converted into a code/repo
 * embed using server-side GitHub metadata instead of the generic website card.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
  createSignupLogger,
  archiveExistingScreenshots,
  createStepScreenshotter,
  getTestAccount
} = require('./signup-flow-helpers');
const {
  loginToTestAccount,
  startNewChat,
  sendMessage,
  deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { waitForEmbedFinished, openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const SAMPLE_REPO = {
  url: 'https://github.com/lemmingDev/ESP32-BLE-Gamepad',
  html_url: 'https://github.com/lemmingDev/ESP32-BLE-Gamepad',
  full_name: 'lemmingDev/ESP32-BLE-Gamepad',
  owner_login: 'lemmingDev',
  owner_avatar_url: 'https://avatars.githubusercontent.com/u/15526971?v=4',
  name: 'ESP32-BLE-Gamepad',
  description: 'Bluetooth LE Gamepad library for the ESP32',
  visibility: 'public',
  private: false,
  fork: false,
  archived: false,
  disabled: false,
  is_template: false,
  default_branch: 'master',
  primary_language: 'C++',
  languages: [{ language: 'C++', bytes: 100177, percent: 100 }],
  topics: [],
  license_name: 'MIT License',
  license_spdx_id: 'MIT',
  stars: 1516,
  forks: 250,
  watchers: 1516,
  subscribers: 48,
  open_issues: 35,
  created_at: '2019-09-14T08:27:14Z',
  updated_at: '2026-05-08T09:02:54Z',
  pushed_at: '2026-04-07T23:53:27Z',
  latest_release_tag: 'v0.7.3',
  latest_release_name: 'Release 7.3',
  latest_release_published_at: '2025-02-15T04:22:16Z',
  latest_commit_sha: '266ec658600f2e0d9d3703939066556577f9d9b3',
  latest_commit_message: 'Fix out-of-range check in specialButtonBitPosition',
  latest_commit_date: '2026-04-07T23:53:27Z',
  contributors: [
    { login: 'lemmingDev', avatar_url: 'https://avatars.githubusercontent.com/u/15526971?v=4', html_url: 'https://github.com/lemmingDev', contributions: 254 },
    { login: 'LeeNX', avatar_url: 'https://avatars.githubusercontent.com/u/792948?v=4', html_url: 'https://github.com/LeeNX', contributions: 26 }
  ],
  site_name: 'GitHub',
  fetched_at: '2026-05-09T00:00:00Z'
};

test.describe('Embed: GitHub code repo', () => {
  test.setTimeout(180_000);

  test('pasted GitHub repo URL creates code repo embed and fullscreen', async ({ page }: { page: any }) => {
    test.skip(!getTestAccount().email, 'Test account credentials required.');

    const logCheckpoint = createSignupLogger('code-repo-embed');
    await archiveExistingScreenshots(logCheckpoint);
    const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

    await page.route('**/api/v1/github-repo?**', async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SAMPLE_REPO)
      });
    });

    await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
    await startNewChat(page, logCheckpoint);

    await sendMessage(
      page,
      SAMPLE_REPO.url,
      logCheckpoint,
      takeStepScreenshot,
      'code-repo'
    );

    const repoEmbed = await waitForEmbedFinished(page, 'code', 'repo', 60_000);
    await expect(repoEmbed.getByTestId('code-repo-title')).toContainText('ESP32-BLE-Gamepad');
    await expect(repoEmbed).toContainText('1.5k');
    await expect(repoEmbed).toContainText('C++');

    const fullscreenOverlay = await openFullscreen(page, repoEmbed);
    await expect(fullscreenOverlay.getByTestId('code-repo-fullscreen')).toBeVisible({ timeout: 10_000 });
    await expect(fullscreenOverlay).toContainText('lemmingDev/ESP32-BLE-Gamepad');
    await expect(fullscreenOverlay).toContainText('MIT');
    await expect(fullscreenOverlay).toContainText('v0.7.3');

    await closeFullscreen(page, fullscreenOverlay);
    await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'code-repo');
  });
});
