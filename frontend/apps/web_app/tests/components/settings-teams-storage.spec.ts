import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = '/dev/preview/settings/SettingsTeams?theme=light&background=%23dbeafe&width=390&chrome=0';

// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
test('successful Team deletion leaves the deleted Team settings route', async ({ page }) => {
  let deleteRequests = 0;
  await page.route('**/v1/teams/first-team', route => {
    expect(route.request().method()).toBe('DELETE');
    deleteRequests += 1;
    return route.fulfill({ json: { success: true } });
  });
  await page.goto('/dev/preview/settings/SettingsTeamsRaceHarness?theme=light&background=%23dbeafe&width=390&chrome=0');
  const canvas = await waitForComponentPreview(page);
  await canvas.getByTestId('team-preview-delete').click();
  await expect(canvas.getByTestId('team-delete-submit')).toBeDisabled();
  await canvas.getByRole('checkbox', {
    name: 'I understand this team will be permanently deleted', exact: true,
  }).check();
  await canvas.getByTestId('team-delete-submit').click();
  await expect(canvas.getByTestId('team-preview-active-route')).toHaveAttribute('data-active-view', 'teams');
  await expect(canvas.getByTestId('team-delete-submit')).toHaveCount(0);
  expect(deleteRequests).toBe(1);
  const bounds = await canvas.getByTestId('team-preview-active-route').boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
});

// contract-test: direct surface=gui.web assertions=billing.storage.weekly-quote,billing.storage.team-policy-gate
// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
test('team storage preview states separate price quote from enabled billing', async ({ page }) => {
  await page.goto(`${preview}&variant=owner`);
  const canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-summary')).toContainText('3 credits / week');
  await expect(canvas.getByTestId('team-storage-policy')).toContainText('Sundays at 03:00 UTC');
  await expect(canvas.getByTestId('team-storage-preview')).toContainText('not yet enabled');
  await expect(canvas.getByTestId('team-storage-active-notice')).toHaveCount(0);
  const layout = await canvas.locator('.settings-page-container').evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  expect(layout.scroll).toBeLessThanOrEqual(layout.client + 1);
});

// contract-test: direct surface=gui.web assertions=billing.storage.team-policy-gate
test('team storage quote is available to admins and hidden from viewers', async ({ page }) => {
  await page.goto(`${preview}&variant=admin`);
  let canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-summary')).toBeVisible();
  await page.goto(`${preview}&variant=viewer`);
  canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-summary')).toHaveCount(0);
  await expect(canvas.getByTestId('team-storage-policy')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=billing.storage.team-warning-expiry
// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
test('team storage notice previews delivered warnings and paginates affected units', async ({ page }) => {
  const second = { unit_id: 'b'.repeat(64), kind: 'artifact_history', resource_id: 'artifact-2',
    oldest_at: 1_700_000_100, bytes: 268_435_456, fingerprint: 'preview-2' };
  await page.route('**/v1/teams/preview-team/storage/notice?**', route => route.fulfill({ json: {
    episode_id: 'episode-1', warning_count: 3, deadline_at: 1_791_936_000, manual_review: false,
    unit_selection_hash: 'preview', units: [second], has_more: false, next_after_unit_id: null,
  } }));
  await page.goto(`${preview}&variant=notice`);
  const canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-active-notice')).toContainText('four delivered weekly warning rounds');
  await expect(canvas.getByTestId('team-storage-affected-unit')).toHaveCount(1);
  const more = canvas.getByTestId('team-storage-load-more');
  await more.focus();
  await expect(more).toBeFocused();
  await more.press('Enter');
  await expect(canvas.getByTestId('team-storage-affected-unit')).toHaveCount(2);
  await expect(more).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=billing.storage.team-warning-expiry,billing.storage.team-policy-gate
test('a delayed old team notice cannot block or replace the selected team notice', async ({ page }) => {
  const storageFor = (team: string) => ({ storage: {
    total_bytes: 1_610_612_736, legacy_upload_bytes: 0, logical_s3_bytes: 1_610_612_736,
    categories: { cold_chat_graphs: 1_610_612_736 }, measurement_at: 1_791_072_000,
    metering_source_version: 'logical-s3-v1', metering_policy_version: 'team-storage-1gb-3credits-week-v1',
    free_bytes: 1_073_741_824, credits_per_started_excess_gib_per_week: 3, billable_gib: 1,
    weekly_cost_credits: 3, billing_status: 'unpaid',
    billing: { status: 'unpaid', warning_count: team === 'first' ? 4 : 2, deadline_at: 1_791_936_000,
      expiry_due: false, expiry_enabled: false, affected_units: [], has_more_affected_units: false },
  } });
  await page.route('**/v1/teams/first-team/storage', route => route.fulfill({ json: storageFor('first') }));
  await page.route('**/v1/teams/second-team/storage', route => route.fulfill({ json: storageFor('second') }));
  let releaseFirst!: () => void;
  let firstStarted!: () => void;
  let firstCompleted!: () => void;
  const firstGate = new Promise<void>(resolve => { releaseFirst = resolve; });
  const firstRequest = new Promise<void>(resolve => { firstStarted = resolve; });
  const firstDone = new Promise<void>(resolve => { firstCompleted = resolve; });
  await page.route('**/v1/teams/first-team/storage/notice?**', async route => {
    firstStarted();
    await firstGate;
    await route.fulfill({ json: { episode_id: 'old-episode', warning_count: 4, deadline_at: 1_791_936_000,
      manual_review: false, unit_selection_hash: 'old', units: [], has_more: false, next_after_unit_id: null } });
    firstCompleted();
  });
  await page.route('**/v1/teams/second-team/storage/notice?**', route => route.fulfill({ json: {
    episode_id: 'new-episode', warning_count: 2, deadline_at: 1_791_936_000,
    manual_review: false, unit_selection_hash: 'new', units: [], has_more: false, next_after_unit_id: null,
  } }));
  await page.goto('/dev/preview/settings/SettingsTeamsRaceHarness?theme=light&background=%23dbeafe&width=390&chrome=0');
  const canvas = await waitForComponentPreview(page);
  await firstRequest;
  await canvas.getByTestId('team-preview-switch').click();
  await expect(canvas.getByTestId('team-settings-header')).toContainText('Second team');
  await expect(canvas.getByTestId('teams-settings-detail')).toContainText('2 / 4');
  releaseFirst();
  await firstDone;
  await expect(canvas.getByTestId('teams-settings-detail')).toContainText('2 / 4');
});

const previewUrl =
  "/dev/preview/enter_message/MessageInputEmbedPersistencePreviewHarness?theme=light&background=%23dbeafe&width=680&chrome=0";

async function openCodeDraft(page: import("@playwright/test").Page, allowSend = false) {
  // The fixture uses a local code-embed persistence mock; no anonymous send is available.
  await page.route("**/v1/anonymous/free-usage/status**", (route) =>
    route.fulfill({
      json: { active: allowSend, can_send_text: allowSend, reason: null },
    }),
  );
  await page.route("**/v1/settings/server-status", (route) =>
    route.fulfill({
      json: {
        is_self_hosted: false,
        payment_enabled: true,
        server_edition: "development",
        ai_models_configured: true,
        anonymous_free_usage: {
          active: allowSend,
          can_send_text: allowSend,
          reason: null,
        },
      },
    }),
  );
  await page.goto(previewUrl);
  await waitForComponentPreview(page);
  const fixture = page.getByTestId("code-persistence-fixture");
  await expect(fixture).toHaveAttribute("data-ready", "true");
  await expect(fixture).toHaveAttribute("data-persistence", "pending");
  await expect(fixture).toHaveAttribute("data-ref", /^preview:code-code:/);
  await expect(fixture).toHaveAttribute("data-code", "const answer = 42;");
  return fixture;
}

test.describe("Closed fenced-code embed persistence before send", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,drafts.persistence.local-first-encrypted
  test("disables Send during a held preparation and preserves newer text after failed transport", async ({ page }) => {
    let transportAttempts = 0;
    await page.route("**/v1/anonymous/chat/stream**", (route) => {
      transportAttempts += 1;
      return route.fulfill({
        status: 503,
        json: { detail: "Synthetic transport failure" },
      });
    });
    const fixture = await openCodeDraft(page, true);
    const send = page.getByTestId("composer-send-button");
    const editor = page.getByTestId("message-editor").locator(".ProseMirror");
    await expect(send).toBeEnabled();
    // The harness sends the same custom-send-message event used by the mounted
    // composer, and its counter proves the real send handler entered readiness.
    await page.getByTestId("fixture-send").click();
    await expect.poll(async () => Number(await fixture.getAttribute("data-readiness-checks"))).toBeGreaterThan(0);
    await expect(fixture).toHaveAttribute("data-persistence", "pending");
    await expect(send).toBeDisabled();
    await expect(fixture).toHaveAttribute("data-send-requests", "0");
    expect(transportAttempts).toBe(0);

    const trailingParagraph = editor.locator(":scope > p").last();
    await expect(trailingParagraph).toContainText("Draft tail");
    await trailingParagraph.click();
    await editor.press("End");
    await page.keyboard.type(" New text typed while sending");
    await expect(editor).toContainText("New text typed while sending");
    await page.getByTestId("fixture-resolve").click();
    await expect(send).toBeEnabled();
    await expect(editor).toContainText("New text typed while sending");
    // sendMessage is dispatched from anonymous onPending before transport is
    // accepted; one callback proves the stored ref and fresh text were prepared.
    await expect(fixture).toHaveAttribute("data-send-requests", "1");
    const preparedContent = await fixture.getAttribute("data-sent-content");
    expect(preparedContent).toContain('"type": "code"');
    expect(preparedContent).toMatch(/"embed_id": "[^"]+"/);
    expect(preparedContent).toContain("Draft tail New text typed while sending");
    expect(preparedContent).not.toContain("preview:code-code:");
    await expect.poll(() => transportAttempts).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  test("immediate Send waits for local persistence and upgrades the draft reference", async ({
    page,
  }) => {
    const fixture = await openCodeDraft(page);
    await page.getByTestId("fixture-send").click();
    await expect
      .poll(async () =>
        Number(await fixture.getAttribute("data-readiness-checks")),
      )
      .toBeGreaterThan(0);
    await expect(fixture).toHaveAttribute("data-persistence", "pending");
    await expect(fixture).toHaveAttribute("data-ref", /^preview:code-code:/);
    await expect(fixture).toHaveAttribute("data-send-requests", "0");

    await page.getByTestId("fixture-resolve").click();
    await expect(fixture).toHaveAttribute("data-ref", /^embed:/);
    await expect(fixture).toHaveAttribute("data-send-requests", "0");
    await expect(fixture).toHaveAttribute(
      "data-sent-content",
      /^(?!.*preview:code-code:)/,
    );
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked,drafts.persistence.local-first-encrypted
  test("failed persistence keeps the code draft and prevents transient-reference send", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    const fixture = await openCodeDraft(page);
    await page.getByTestId("fixture-send").click();
    await expect
      .poll(async () =>
        Number(await fixture.getAttribute("data-readiness-checks")),
      )
      .toBeGreaterThan(0);
    await expect(fixture).toHaveAttribute("data-persistence", "pending");
    await expect(fixture).toHaveAttribute("data-send-requests", "0");

    await page.getByTestId("fixture-reject").click();
    await expect
      .poll(() =>
        errors.some((message) =>
          message.includes(
            "Code/document preview is not stored; keeping draft unsent",
          ),
        ),
      )
      .toBe(true);
    await expect(fixture).toHaveAttribute("data-ref", /^preview:code-code:/);
    await expect(fixture).toHaveAttribute("data-code", "const answer = 42;");
    await expect(fixture).toHaveAttribute("data-send-requests", "0");
  });
});

// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,drafts.sync.version-authoritative
test('local fenced code renders from inline content while its embed is pending', async ({
	page
}) => {
	const embedRequests: string[] = [];
	page.on('request', (request) => {
		if (new URL(request.url()).pathname.startsWith('/v1/embeds/')) {
			embedRequests.push(request.url());
		}
	});
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(
		'/dev/preview/embeds/code/CodeEmbedPreview?variant=localFencedCode&chrome=0&theme=light&background=%23dbeafe&width=350'
	);
	await waitForComponentPreview(page);
	const codeCard = page.locator('.unified-embed-preview');
	await expect(codeCard).toBeVisible();
	await expect(codeCard).toContainText('local_preview_value');
	await expect(codeCard).not.toContainText('Error loading embed');
	expect(embedRequests).toEqual([]);
});
