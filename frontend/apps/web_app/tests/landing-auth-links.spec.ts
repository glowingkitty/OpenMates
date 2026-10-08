import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getE2EDebugUrl, getIsolatedTestAccount } = require('./signup-flow-helpers');

const account = getIsolatedTestAccount('landing-auth-links.spec.ts');
const stagedPath = '/signup/secure-account';

/** Change one field on this runner's fresh synthetic account; preserve its prior value. */
function changeIsolatedLastOpened(email: string, expected: string | null, next: string): string {
  const base = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'http://invalid');
  if (process.env.OPENMATES_CI_ISOLATED !== '1' || process.env.GITHUB_ACTIONS !== 'true'
    || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e'
    || base.origin !== 'http://localhost:5173' || !/^ci-[a-z0-9-]+@example\.com$/.test(email)) {
    throw new Error('Signup-stage fixture requires a fresh runner-local synthetic account');
  }
  const root = path.resolve(__dirname, '../../../..');
  const script = `
import asyncio, base64, hashlib, json, os, sys
import requests
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService

assert os.environ.get('CI') == 'true'
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
assert os.environ.get('FRONTEND_URLS') == 'http://localhost:5173'
assert os.environ.get('CMS_URL') == 'http://cms:8055'
email, expected_json, next_path = sys.argv[1:4]
assert email.startswith('ci-') and email.endswith('@example.com')
assert next_path in ('/signup/secure-account', '/chat/new') or not next_path.startswith('/signup/')
expected = json.loads(expected_json)
login = requests.post('http://cms:8055/auth/login', json={
    'email': os.environ['DATABASE_ADMIN_EMAIL'],
    'password': os.environ['DATABASE_ADMIN_PASSWORD'],
}, timeout=15)
login.raise_for_status()
token = login.json()['data']['access_token']
headers = {'Authorization': 'Bearer ' + token}
identity = requests.get('http://cms:8055/users/me', headers=headers, timeout=15)
identity.raise_for_status()
assert identity.json()['data']['email'] == os.environ['DATABASE_ADMIN_EMAIL']
hashed = base64.b64encode(hashlib.sha256(email.lower().encode()).digest()).decode()
result = requests.get('http://cms:8055/users', headers=headers, params={
    'filter[hashed_email][_eq]': hashed,
    'fields': 'id,email,hashed_email,last_opened,signup_completed',
    'limit': '2',
}, timeout=15)
result.raise_for_status()
users = result.json()['data']
assert len(users) == 1 and users[0]['hashed_email'] == hashed
assert users[0]['email'] == hashed[:64] + '@example.com'
assert users[0]['signup_completed'] is False
previous = users[0].get('last_opened')
if expected is None:
    assert isinstance(previous, str) and previous and not previous.startswith(('/signup/', '#signup/'))
else:
    assert previous == expected

async def change():
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        try:
            assert await directus.update_user(users[0]['id'], {'last_opened': next_path})
        except BaseException:
            await directus.update_user(users[0]['id'], {'last_opened': previous})
            raise
    finally:
        await directus.close()
        await cache.close()

asyncio.run(change())
print(json.dumps({'previous': previous}))
`;
  const output = execFileSync('docker', [
    'compose', '-f', path.join(root, 'test-results/ci-private/compose.json'),
    'exec', '-T', '-e', 'CI=true', '-e', 'OPENMATES_CI_ISOLATED=1',
    'api', 'python', '-c', script, email, JSON.stringify(expected), next,
  ], { cwd: root, encoding: 'utf8', timeout: 45_000 });
  return (JSON.parse(output.trim().split('\n').at(-1) ?? '') as { previous: string }).previous;
}

function observeAccountFlash(): void {
  const observed: string[] = [];
  (window as Window & { __authLinkFlash?: string[] }).__authLinkFlash = observed;
  const record = () => {
    for (const id of ['signup-modal', 'login-wrapper']) {
      if (document.querySelector(`[data-testid="${id}"]`) && !observed.includes(id)) observed.push(id);
    }
  };
  new MutationObserver(record).observe(document, { childList: true, subtree: true });
  record();
}

async function expectChatsWithoutAccountFlash(page: import('@playwright/test').Page): Promise<void> {
  await expect(page.locator('[data-testid="active-chat-container"][data-authenticated="true"]')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('signup-modal')).toHaveCount(0);
  await expect(page.getByTestId('login-wrapper')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() =>
    (window as Window & { __authLinkFlash?: string[] }).__authLinkFlash ?? []
  )).toEqual([]);
  await expect(page).not.toHaveURL(/#signup\//);
}

/** Exercise the real startup profile cache while leaving the server account completed. */
async function replaceCachedLastOpened(page: import('@playwright/test').Page, next: string): Promise<string> {
  return page.evaluate(async path => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('user_db');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      const previous = await new Promise<string>((resolve, reject) => {
        const request = db.transaction('user_data', 'readonly').objectStore('user_data').get('last_opened');
        request.onsuccess = () => resolve(String(request.result ?? ''));
        request.onerror = () => reject(request.error);
      });
      await new Promise<void>((resolve, reject) => {
        const transaction = db.transaction('user_data', 'readwrite');
        transaction.objectStore('user_data').put(path, 'last_opened');
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });
      return previous;
    } finally {
      db.close();
    }
  }, next);
}

test.describe('landing account links with real authentication', () => {
  test.describe.configure({ mode: 'serial' });

  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations
  test('completed account opens Chats from warm and cold signup links without an account flash', async ({ page }) => {
    test.setTimeout(180_000);
    test.skip(!account.email || !account.password || !account.otpKey, 'Isolated test account credentials required.');
    await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials: account });
    await expect(page.locator('[data-testid="active-chat-container"][data-authenticated="true"]')).toBeVisible();

    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
    await page.evaluate(observeAccountFlash);
    await page.evaluate(() => { (window as Window & { __authLinkWarm?: boolean }).__authLinkWarm = true; });
    await page.getByTestId('landing-signup').click();
    expect(await page.evaluate(() => (window as Window & { __authLinkWarm?: boolean }).__authLinkWarm)).toBe(true);
    await expectChatsWithoutAccountFlash(page);

    await page.addInitScript(observeAccountFlash);
    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
    const signupHref = await page.getByTestId('landing-signup').getAttribute('href');
    expect(signupHref).toMatch(/#signup\/basics$/);
    await page.evaluate(() => { (window as Window & { __authLinkLanding?: boolean }).__authLinkLanding = true; });
    await page.goto(signupHref!, { waitUntil: 'domcontentloaded' });
    expect(await page.evaluate(() => (window as Window & { __authLinkLanding?: boolean }).__authLinkLanding)).toBeUndefined();
    await expectChatsWithoutAccountFlash(page);
  });

  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations
  test('stale cached signup stage cannot flash signup for a completed account', async ({ page }) => {
    test.setTimeout(180_000);
    test.skip(!account.email || !account.password || !account.otpKey, 'Isolated test account credentials required.');
    await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials: account });
    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
    const previous = await replaceCachedLastOpened(page, stagedPath);
    try {
      await page.addInitScript(observeAccountFlash);
      const signupHref = await page.getByTestId('landing-signup').getAttribute('href');
      expect(signupHref).toMatch(/#signup\/basics$/);
      await page.evaluate(() => { (window as Window & { __authLinkLanding?: boolean }).__authLinkLanding = true; });
      const sessionCheck = page.waitForResponse(response =>
        response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/v1/auth/session')
      );
      await page.goto(signupHref!, { waitUntil: 'domcontentloaded' });
      expect(await page.evaluate(() => (window as Window & { __authLinkLanding?: boolean }).__authLinkLanding)).toBeUndefined();
      const response = await sessionCheck;
      expect(response.ok()).toBe(true);
      expect(String((await response.json()).user.last_opened ?? '')).not.toMatch(/^\/?#?signup\//);
      await expectChatsWithoutAccountFlash(page);
    } finally {
      await replaceCachedLastOpened(page, previous);
    }
  });

  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations
  test('an authenticated account resumes its saved incomplete signup stage', async ({ page }) => {
    test.setTimeout(180_000);
    test.skip(!account.email || !account.password || !account.otpKey, 'Isolated test account credentials required.');
    await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials: account });
    const previous = changeIsolatedLastOpened(account.email!, null, stagedPath);
    try {
      await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
      const signupHref = await page.getByTestId('landing-signup').getAttribute('href');
      expect(signupHref).toMatch(/#signup\/basics$/);
      await page.evaluate(() => { (window as Window & { __authLinkLanding?: boolean }).__authLinkLanding = true; });
      const sessionCheck = page.waitForResponse(response =>
        response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/v1/auth/session')
      );
      await page.goto(signupHref!, { waitUntil: 'domcontentloaded' });
      expect(await page.evaluate(() => (window as Window & { __authLinkLanding?: boolean }).__authLinkLanding)).toBeUndefined();
      const response = await sessionCheck;
      expect(response.ok()).toBe(true);
      expect((await response.json()).user.last_opened).toBe(stagedPath);
      await expect(page.getByTestId('signup-modal')).toBeVisible({ timeout: 30_000 });
      await expect(page.locator('#signup-passkey-option')).toBeVisible({ timeout: 30_000 });
      await expect(page.locator('input[type="email"][autocomplete="email"]')).toHaveCount(0);
    } finally {
      changeIsolatedLastOpened(account.email!, stagedPath, previous);
    }
  });
});
