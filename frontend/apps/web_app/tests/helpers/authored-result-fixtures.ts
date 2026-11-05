/**
 * Account-free UI fixtures reuse the deterministic backend authoring catalogue.
 * These are saved-content presentation inputs, not persistence/normalizer proof.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';
import { waitForComponentPreview } from './component-preview';

const ROOT = path.resolve(__dirname, '../../../../..');
const fixture = JSON.parse(readFileSync(path.join(ROOT,
  'backend/apps/ai/testing/fixtures/authored_results.json'), 'utf8'));
export const authoredDocument = (Object.values(fixture.embeds)[0] as { document: {
  title: string; items: AuthoredFixtureItem[];
} }).document;
export interface AuthoredFixtureItem {
  id: string; kind: string; title: string; origin: 'user_provided' | 'researched' | 'draft';
  details: Record<string, unknown>; sources?: Array<{ url?: string; label?: string; embed_ref?: string }>;
  observed_at?: string;
}
export const authoredDefinitions = JSON.parse(readFileSync(path.join(ROOT,
  'shared/config/authored_result_types.json'), 'utf8')).kinds as Record<string, {
  backend_type: string; app_id: string; skill_id: string;
}>;
export const authoredChildren = authoredDocument.items.map((item, index) => ({
  embed_id: `777d0000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  content: {
    ...item.details, type: authoredDefinitions[item.kind].backend_type,
    app_id: authoredDefinitions[item.kind].app_id, skill_id: authoredDefinitions[item.kind].skill_id,
    title: item.title, status: 'finished', embed_ref: `${item.id}-fixture`,
    authoring: { schema_version: 1, kind: item.kind, origin: item.origin,
      sources: item.sources ?? [], ...(item.observed_at ? { observed_at: item.observed_at } : {}) },
  } as Record<string, unknown>,
}));
export function authoredChild(kind: string) {
  const child = authoredChildren.find(value => value.content.authoring
    && (value.content.authoring as { kind: string }).kind === kind);
  if (!child) throw new Error(`Missing authored fixture kind ${kind}`);
  return child;
}
export async function openAuthoredComponent(page: Page, component: string, {
  width = 1100, theme = 'light', variant, props, context,
}: { width?: number; theme?: 'light' | 'dark'; variant?: string; props?: Record<string, unknown>; context?: 'chat' } = {}) {
  await page.setViewportSize({ width, height: 900 });
  const query = new URLSearchParams({ chrome: '0', width: String(width), theme, background: theme === 'dark' ? '#18202c' : '#dbeafe' });
  if (variant) query.set('variant', variant);
  if (context) query.set('context', context);
  if (props) query.set('props', JSON.stringify(props));
  await page.goto(`/dev/preview/embeds/${component}?${query}`);
  await waitForComponentPreview(page);
}
export async function isolateAuthoredImages(page: Page, fail = false) {
  const response = await page.request.get('/images/examples/group1.jpg');
  expect(response.ok()).toBe(true);
  const body = await response.body();
  await page.route('**/api/v1/image?*', route => fail
    ? route.fulfill({ status: 404, body: '' })
    : route.fulfill({ contentType: 'image/jpeg', body }));
  await page.route('https://*.tile.openstreetmap.org/**', route => route.fulfill({ contentType: 'image/jpeg', body }));
  await page.route('**/api/v1/metadata?*', route => route.fulfill({ json: {} }));
  await page.route('**/api/v1/youtube?*', route => route.fulfill({ json: {} }));
}
export async function assertReadableAuthoredBounds(page: Page, surface: Locator) {
  await expect(surface).toBeVisible();
  const bounds = await surface.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.width).toBeGreaterThan(100);
  expect(bounds!.x).toBeGreaterThanOrEqual(-1);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
}
export async function authoredCapture(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
}
