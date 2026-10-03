// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (width: number, variant?: string) =>
  `/dev/preview/apps/AppsSkillForm?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
test('Apps skill form keeps two primary controls and preserves request shape', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(preview(760));
  await waitForComponentPreview(page);
  const form = page.getByTestId('apps-skill-form');
  await expect(form).toBeVisible();
  await expect(page.getByTestId('apps-skill-execution-meta')).toHaveCount(0);
  await expect(page.getByTestId('apps-skill-settings')).toHaveCount(0);
  await expect(page.getByTestId('apps-skill-primary-fields').locator('.schema-field')).toHaveCount(2);
  const formBox = await form.boundingBox();
  expect(formBox).not.toBeNull();
  expect(formBox!.width).toBeLessThanOrEqual(760);
  await expect(page.getByTestId('apps-skill-settings-toggle')).toHaveAttribute('aria-expanded', 'false');
  await form.getByLabel('What').fill('jazz');
  await form.getByLabel('Where').fill('Hamburg');
  await page.getByTestId('apps-skill-settings-toggle').click();
  await expect(page.getByTestId('apps-skill-settings-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('apps-skill-settings')).toBeVisible();
  await page.evaluate(() => {
    (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput = undefined;
    window.addEventListener('apps-skill-preview-submit', event => {
      (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput = (event as CustomEvent).detail;
    }, { once: true });
  });
  await page.getByTestId('apps-skill-submit').click();
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput)).toEqual({
    requests: [{ query: 'jazz', location: 'Hamburg', start_date: '2026-10-01', end_date: '2026-10-07' }], provider: 'default',
  });
});

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
test('Events exposes native optional requirements outside settings and submits relevance criteria', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview(390));
  await waitForComponentPreview(page);
  const form = page.getByTestId('apps-skill-form');
  const requirements = page.getByTestId('apps-skill-requirements');
  const textarea = page.getByTestId('apps-skill-relevance-criteria');
  await expect(requirements).toBeVisible();
  await expect(requirements.getByText('Requirements')).toBeVisible();
  await expect(textarea).toBeVisible();
  await expect(textarea).toHaveAttribute('maxlength', '1000');
  await expect(page.getByTestId('apps-skill-settings')).toHaveCount(0);
  const formBox = await form.boundingBox();
  const fieldBox = await textarea.boundingBox();
  expect(formBox && fieldBox).toBeTruthy();
  expect(fieldBox!.x).toBeGreaterThanOrEqual(formBox!.x);
  expect(fieldBox!.x + fieldBox!.width).toBeLessThanOrEqual(formBox!.x + formBox!.width + 1);

  await form.getByLabel('What').fill('AI');
  await form.getByLabel('Where').fill('Berlin');
  await textarea.fill('Events where I can meet potential users and give a future talk.');
  await page.getByTestId('apps-skill-settings-toggle').click();
  await expect(page.getByTestId('apps-skill-settings').getByTestId('apps-skill-relevance-criteria')).toHaveCount(0);
  await page.evaluate(() => window.addEventListener('apps-skill-preview-submit', event => {
    (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput = (event as CustomEvent).detail;
  }, { once: true }));
  await page.getByTestId('apps-skill-submit').click();
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput)).toEqual({
    requests: [{ query: 'AI', location: 'Berlin', relevance_criteria: 'Events where I can meet potential users and give a future talk.', start_date: '2026-10-01', end_date: '2026-10-07' }],
    provider: 'default',
  });
});

// contract-test: direct surface=gui.web assertions=apps.anonymous.cli-equivalent-gate
test('ineligible guest sees signup before any skill request', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview(390, 'guestBlocked'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-skill-signup')).toBeVisible();
  await expect(page.getByTestId('apps-skill-submit')).toHaveCount(0);
  const form = page.getByTestId('apps-skill-form');
  const box = await form.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(391);
  await page.getByTestId('apps-skill-settings-toggle').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('apps-skill-settings')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
test('Travel keeps origin and destination as two primary controls and requires date in settings', async ({ page }) => {
  await page.goto(preview(760, 'travel'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-skill-requirements')).toHaveCount(0);
  const primary = page.getByTestId('apps-skill-primary-fields');
  await expect(primary.locator('.schema-field--specialized')).toHaveCount(2);
  await expect(page.getByTestId('apps-skill-settings')).toHaveCount(0);
  await primary.getByRole('textbox', { name: 'Origin' }).fill('Munich');
  await primary.getByRole('textbox', { name: 'Destination' }).fill('Berlin');
  await page.getByTestId('apps-skill-submit').click();
  await expect(page.getByTestId('apps-skill-validation-errors')).toContainText('date');
  await expect(page.getByTestId('apps-skill-settings')).toBeVisible();
  await page.getByTestId('apps-skill-settings').getByLabel('Departure date').fill('2026-10-15');
  await page.evaluate(() => window.addEventListener('apps-skill-preview-submit', event => {
    (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput = (event as CustomEvent).detail;
  }, { once: true }));
  await page.getByTestId('apps-skill-submit').click();
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput)).toEqual({
    requests: [{ legs: [{ origin: 'Munich', destination: 'Berlin', date: '2026-10-15' }], transport_methods: ['airplane'] }],
  });
});

// contract-test: direct surface=gui.web assertions=apps.anonymous.cli-equivalent-gate,apps.forms.metadata-driven
test('Guest Travel validates a hidden required date before quoting the route or executing', async ({ page }) => {
  let availabilityPosts = 0;
  let executionPosts = 0;
  await page.route('**/v1/anonymous/apps/travel/skills/search_connections/availability', async route => {
    availabilityPosts += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ allowed: true, reason: null }) });
  });
  await page.route('**/v1/anonymous/apps/travel/skills/search_connections', async route => {
    executionPosts += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.goto(preview(760, 'travelGuest'));
  await waitForComponentPreview(page);
  // The SDK schema permits an empty optional legs array, so its declared
  // defaults can receive an initial quote. Editing a partial leg must not.
  await expect.poll(() => availabilityPosts).toBe(1);
  const initialAvailabilityPosts = availabilityPosts;
  await page.evaluate(() => {
    (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions = [];
    window.addEventListener('apps-skill-preview-submit', event => {
      (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions?.push((event as CustomEvent).detail);
    });
  });
  const primary = page.getByTestId('apps-skill-primary-fields');
  await primary.getByRole('textbox', { name: 'Origin' }).fill('Munich');
  await primary.getByRole('textbox', { name: 'Destination' }).fill('Berlin');
  await expect(page.getByTestId('apps-skill-submit')).toBeEnabled();
  await page.getByTestId('apps-skill-submit').click();
  await expect(page.getByTestId('apps-skill-validation-errors')).toContainText('date');
  await expect(page.getByTestId('apps-skill-settings')).toBeVisible();
  expect(availabilityPosts).toBe(initialAvailabilityPosts);
  expect(executionPosts).toBe(0);
  expect(await page.evaluate(() => (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions)).toEqual([]);

  await page.getByTestId('apps-skill-settings').getByLabel('Departure date').fill('2026-10-15');
  await expect.poll(() => availabilityPosts).toBe(initialAvailabilityPosts + 1);
  await expect(page.getByTestId('apps-skill-submit')).toBeEnabled();
  await page.getByTestId('apps-skill-submit').click();
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions)).toEqual([
    { requests: [{ legs: [{ origin: 'Munich', destination: 'Berlin', date: '2026-10-15' }], transport_methods: ['airplane'] }] },
  ]);
  expect(executionPosts).toBe(0);
});

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
test('Stay date range is one primary control and submits literal dates', async ({ page }) => {
  await page.goto(preview(760, 'stays'));
  await waitForComponentPreview(page);
  const primary = page.getByTestId('apps-skill-primary-fields');
  await expect(primary.locator('.schema-field')).toHaveCount(2);
  await primary.getByRole('textbox', { name: 'Destination' }).fill('Hotels in Paris');
  await primary.getByTestId('workflow-date-range-today').click();
  await page.evaluate(() => window.addEventListener('apps-skill-preview-submit', event => {
    (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput = (event as CustomEvent).detail;
  }, { once: true }));
  await page.getByTestId('apps-skill-submit').click();
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __appsPreviewInput?: { requests?: Array<Record<string, unknown>> } }).__appsPreviewInput)).not.toBeUndefined();
  const request = await page.evaluate(() => (window as typeof window & { __appsPreviewInput?: { requests?: Array<Record<string, unknown>> } }).__appsPreviewInput?.requests?.[0]);
  expect(request).toMatchObject({ query: 'Hotels in Paris', adults: 2 });
  expect(request?.check_in_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(request?.check_out_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven,apps.presentation.shared-detail-and-recency
test('Audio shows one declared prompt textarea with a nearby coral action and actual provider rate', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(preview(760, 'audioGenerate'));
  await waitForComponentPreview(page);
  const form = page.getByTestId('apps-skill-form');
  await expect(page.getByTestId('apps-skill-manual-intro')).toBeVisible();
  const primary = page.getByTestId('apps-skill-primary-fields');
  await expect(page.getByTestId('apps-skill-requirements')).toHaveCount(0);
  await expect(primary.locator('.schema-field')).toHaveCount(1);
  const prompt = page.getByTestId('apps-skill-textarea-prompt');
  await expect(prompt).toBeVisible();
  await expect(prompt).toHaveAttribute('aria-label', 'Prompt');
  const promptBox = await prompt.boundingBox();
  expect(promptBox).not.toBeNull();
  expect(promptBox!.width).toBeGreaterThan(400);
  const promptLabelBox = await primary.locator('.textarea-field > .field-label').boundingBox();
  expect(promptLabelBox).not.toBeNull();
  expect(promptLabelBox!.width).toBeLessThanOrEqual(1);
  const promptColors = await prompt.evaluate(element => {
    const probe = document.createElement('div');
    probe.style.backgroundColor = 'var(--color-grey-20)';
    document.body.append(probe);
    const colors = { actual: getComputedStyle(element).backgroundColor, token: getComputedStyle(probe).backgroundColor };
    probe.remove();
    return colors;
  });
  expect(promptColors.actual).toBe(promptColors.token);
  await expect(page.getByTestId('apps-skill-settings')).toHaveCount(0);
  const settings = page.getByTestId('apps-skill-settings-toggle');
  const run = page.getByTestId('apps-skill-submit');
  await expect(settings.locator('.settings-icon')).toBeVisible();
  const settingsColors = await settings.evaluate(element => {
    const probe = document.createElement('div');
    probe.style.color = 'var(--color-primary-start)';
    document.body.append(probe);
    const colors = { actual: getComputedStyle(element).color, token: getComputedStyle(probe).color };
    probe.remove();
    return colors;
  });
  expect(settingsColors.actual).toBe(settingsColors.token);
  const settingsBox = await settings.boundingBox();
  const runBox = await run.boundingBox();
  expect(settingsBox).not.toBeNull();
  expect(runBox).not.toBeNull();
  expect(Math.abs(settingsBox!.y - runBox!.y)).toBeLessThan(32);
  expect(runBox!.width).toBeGreaterThanOrEqual(176);
  const buttonColors = await run.evaluate(element => {
    const tokenProbe = document.createElement('div');
    tokenProbe.style.backgroundColor = 'var(--color-button-primary)';
    document.body.append(tokenProbe);
    const colors = { actual: getComputedStyle(element).backgroundColor, token: getComputedStyle(tokenProbe).backgroundColor };
    tokenProbe.remove();
    return colors;
  });
  expect(buttonColors.actual).toBe(buttonColors.token);
  await expect(page.getByTestId('apps-skill-providers')).toContainText('ElevenLabs');
  await expect(page.getByTestId('apps-skill-pricing')).toContainText('20 credits');
  await expect(page.getByTestId('apps-skill-pricing')).toContainText('per second');
  await expect(page.getByTestId('apps-skill-models')).toContainText('ElevenLabs Text to Sound v2');
  const providerBox = await page.getByTestId('apps-skill-providers').boundingBox();
  const pricingBox = await page.getByTestId('apps-skill-pricing').boundingBox();
  const modelBox = await page.getByTestId('apps-skill-models').boundingBox();
  expect(providerBox && pricingBox && modelBox).toBeTruthy();
  expect(pricingBox!.y).toBeGreaterThan(providerBox!.y);
  expect(modelBox!.y).toBeGreaterThan(pricingBox!.y);
  const desktopImage = test.info().outputPath('audio-form-desktop.png');
  await form.screenshot({ path: desktopImage, animations: 'disabled' });
  await test.info().attach('Audio form desktop', { path: desktopImage, contentType: 'image/png' });
  await settings.click();
  await expect(page.getByTestId('apps-skill-settings')).toBeVisible();
  await expect(page.getByTestId('apps-skill-settings').getByLabel(/duration seconds/i)).toHaveValue('1');
  await prompt.fill('Soft rain on leaves');
  await page.evaluate(() => window.addEventListener('apps-skill-preview-submit', event => {
    (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput = (event as CustomEvent).detail;
  }, { once: true }));
  await run.click();
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __appsPreviewInput?: unknown }).__appsPreviewInput)).toEqual({
    requests: [{ prompt: 'Soft rain on leaves', provider: 'elevenlabs', duration_seconds: 1, prompt_influence: 0.3, loop: false, output_format: 'mp3_44100_128', model: 'eleven_text_to_sound_v2' }],
  });
  const formBox = await form.boundingBox();
  expect(formBox).not.toBeNull();
  expect(formBox!.width).toBeLessThanOrEqual(760);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview(390, 'audioGenerate'));
  await waitForComponentPreview(page);
  const mobileImage = test.info().outputPath('audio-form-phone.png');
  await page.getByTestId('apps-skill-form').screenshot({ path: mobileImage, animations: 'disabled' });
  await test.info().attach('Audio form phone', { path: mobileImage, contentType: 'image/png' });
  const mobileForm = await page.getByTestId('apps-skill-form').boundingBox();
  const mobileSettings = await page.getByTestId('apps-skill-settings-toggle').boundingBox();
  const mobileRun = await page.getByTestId('apps-skill-submit').boundingBox();
  expect(mobileForm).not.toBeNull();
  expect(mobileSettings).not.toBeNull();
  expect(mobileRun).not.toBeNull();
  expect(mobileForm!.x).toBeGreaterThanOrEqual(0);
  expect(mobileForm!.x + mobileForm!.width).toBeLessThanOrEqual(391);
  expect(mobileRun!.y).toBeGreaterThan(mobileSettings!.y);
});

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
test('Music shows its declared track price with the translated unit', async ({ page }) => {
  await page.goto(preview(760, 'musicGenerate'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-skill-pricing')).toHaveText('120 credits per track');
  await expect(page.getByTestId('apps-skill-providers')).toContainText('Google');
});

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven,apps.execution.direct-shared-contract
test('Health city picker keeps settings closed and submits native filters only on Run skill', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(() => {
    (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions = [];
    window.addEventListener('apps-skill-preview-submit', event => {
      (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions?.push((event as CustomEvent).detail);
    });
  });
  let berlinSearches = 0;
  let holdNextSearch = false;
  let pendingSearchStarted = false;
  let releaseSearch!: () => void;
  let finishSearch!: () => void;
  const searchGate = new Promise<void>(resolve => { releaseSearch = resolve; });
  const searchFinished = new Promise<void>(resolve => { finishSearch = resolve; });
  await page.route('**/v1/geocode/search?**', async route => {
    const query = new URL(route.request().url()).searchParams.get('q');
    if (query === 'Berlin') berlinSearches += 1;
    const held = holdNextSearch;
    if (held) {
      holdNextSearch = false;
      pendingSearchStarted = true;
      await searchGate;
    }
    try {
      return await route.fulfill({ json: query === 'Berlin' ? [{
        lat: '52.52', lon: '13.405', name: 'Berlin', display_name: 'Berlin, Germany',
        class: 'place', type: 'city', namedetails: { name: 'Berlin' },
        address: { city: 'Berlin', country: 'Germany' },
      }] : [] });
    } finally {
      if (held) finishSearch();
    }
  });
  await page.goto(preview(760, 'health'));
  await waitForComponentPreview(page);
  const form = page.getByTestId('apps-skill-form');
  const settingsToggle = form.getByTestId('apps-skill-settings-toggle');
  const submissions = () => page.evaluate(() => (window as typeof window & { __appsPreviewSubmissions?: unknown[] }).__appsPreviewSubmissions);
  const expectNoPickerSubmit = async () => {
    await expect(settingsToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(form.getByTestId('apps-skill-settings')).toHaveCount(0);
    expect(await submissions()).toEqual([]);
  };
  await form.getByRole('textbox', { name: /Speciality/i }).fill('dermatologist');
  await form.getByTestId('workflow-node-location-picker').click();
  await expect(form.getByTestId('workflow-location-map')).toBeVisible();
  await expectNoPickerSubmit();
  await form.getByTestId('map-location-search-input').fill('Berlin');
  await expect(form.getByTestId('map-location-search-result')).toContainText('Berlin');
  expect(berlinSearches).toBeGreaterThan(0);
  await expectNoPickerSubmit();
  holdNextSearch = true;
  await form.getByTestId('map-location-search-input').press('Enter');
  await expect.poll(() => pendingSearchStarted).toBe(true);
  await expect(form.getByTestId('map-location-search-result')).toContainText('Berlin');
  await expectNoPickerSubmit();
  await form.getByTestId('map-location-search-result').click();
  await expect(form.getByTestId('map-location-select')).toBeEnabled();
  await expectNoPickerSubmit();
  releaseSearch();
  await searchFinished;
  await expect(form.getByTestId('map-location-search-result')).toHaveCount(0);
  const selectedMap = test.info().outputPath('health-city-selection.png');
  await form.screenshot({ path: selectedMap, animations: 'disabled' });
  await test.info().attach('Health selected city', { path: selectedMap, contentType: 'image/png' });
  await form.getByTestId('map-location-select').click();
  await expect(form.getByTestId('workflow-node-location-picker')).toContainText('Berlin');
  await expectNoPickerSubmit();

  await settingsToggle.click();
  await expect(form.getByTestId('apps-skill-settings')).toBeVisible();
  await form.getByRole('combobox', { name: /Insurance Sector/i }).selectOption('public');
  expect(await submissions()).toEqual([]);
  await form.getByTestId('apps-skill-submit').click();
  await expect.poll(submissions).toEqual([{ requests: [{
    speciality: 'dermatologist', city: 'Berlin', provider_platform: 'both',
    insurance_sector: 'public', days_ahead: 7, max_doctors: 10, telehealth: false,
  }] }]);
});
