import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';
import { expectCanonicalMask } from '../helpers/canonical-icon';

// playwright-account: not_required reason=isolated_component_preview

const preview = (variant: string, width = 323) =>
	`/dev/preview/settings/SettingsTeams?theme=light&background=%23dbeafe&width=${width}&chrome=0&variant=${variant}`;

async function expectPhonePreviewFits(page: Page) {
	const teams = page.getByTestId('teams-settings-page');
	await expect(teams).toBeVisible();
	await expect(teams).not.toContainText('[T:');
	await expect(page.getByTestId('team-settings-header')).not.toContainText('[T:');
	await expect(page.getByTestId('team-settings-header').locator('.app-details-header')).toHaveCSS(
		'opacity',
		'1'
	);
	await expect(page.getByTestId('team-settings-header').locator('.app-details-header')).toHaveCSS(
		'background-image',
		/linear-gradient.*rgb\(72, 103, 205\)/
	);
	const geometry = await teams.evaluate((element) => ({
		width: element.clientWidth,
		scrollWidth: element.scrollWidth
	}));
	expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
}

test.describe('Teams settings component', () => {
	// contract-test: direct surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,teams.lifecycle.encrypted-profiled
	test('matches the default Team overview setup artboard', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('detail'));
		await waitForComponentPreview(page);
		await expectPhonePreviewFits(page);
		await expect(page.getByTestId('team-setup-checklist')).toBeVisible();
		await expect(page.getByTestId('team-setup-checklist')).toHaveCSS(
			'background-color',
			'rgb(255, 255, 255)'
		);
		await expect(page.locator('.setup-checkmark')).toHaveCSS('background-color', 'rgb(0, 159, 0)');
		await expect(page.getByTestId('team-settings-header-avatar')).toHaveCSS('width', '53px');
		await expect(
			page.getByTestId('team-billing-open').getByText('Billing & usage', { exact: true })
		).toHaveCSS('font-weight', '700');
		const frame = await page.locator('.teams-frame').boundingBox();
		const card = await page.getByTestId('team-setup-checklist').boundingBox();
		expect(card!.x - frame!.x).toBeCloseTo(19, 0);
		expect(card!.y - frame!.y).toBeCloseTo(244, 0);
		expect(card!.width).toBeCloseTo(286, 0);
		expect(card!.height).toBeGreaterThanOrEqual(245);
		expect(card!.height).toBeLessThanOrEqual(249);
	});

	// contract-test: direct surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,teams.security.join-policy
	test('matches the default Security artboard without an empty domain CTA', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('security'));
		await waitForComponentPreview(page);
		await expectPhonePreviewFits(page);
		await expect(page.getByTestId('team-settings-header').locator('.app-name')).toHaveText(
			'Security'
		);
		await expect(page.getByTestId('team-security-domain-add')).toHaveCount(0);
		const domainLabel = page
			.getByTestId('team-security-domain-toggle')
			.getByText('Domain restriction', { exact: true });
		await expect(domainLabel).toHaveCSS('font-weight', '700');
		const frame = await page.getByTestId('team-settings-header').boundingBox();
		const label = await domainLabel.boundingBox();
		expect(label!.x - frame!.x).toBeCloseTo(75, 0);
		const strongAuth = page.getByTestId('team-security-strong-auth-toggle');
		await expect(strongAuth).toContainText('Passkey/2FA required');
		const strongLabel = await strongAuth
			.getByText('Passkey/2FA required', { exact: true })
			.boundingBox();
		const strongToggle = await strongAuth.getByTestId('toggle-container').boundingBox();
		expect(strongLabel!.height).toBeLessThanOrEqual(21);
		expect(strongLabel!.x + strongLabel!.width).toBeLessThanOrEqual(strongToggle!.x);
		await expectCanonicalMask(
			page.getByTestId('team-settings-header').locator('.banner-mask-icon'),
			'safety'
		);
	});

	// contract-test: direct surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,teams.lifecycle.encrypted-profiled
	test('shows the empty first visit and a populated Teams listing', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('default'));
		await waitForComponentPreview(page);
		await test.step('defaultempty: empty Teams overview and New team control fit the phone', async () => {
			await expect(
				page.getByText('No teams yet. Create one to collaborate securely.', { exact: true })
			).toBeVisible();
			await expect(page.getByTestId('team-settings-team-row')).toHaveCount(0);
			await expect(page.getByTestId('team-create-open')).toBeVisible();
			await expectPhonePreviewFits(page);
		});

		await page.goto(preview('teamsListing'));
		await waitForComponentPreview(page);
		await test.step('allteams: joined teams and New team control fit the phone', async () => {
			const rows = page.getByTestId('team-settings-team-row');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toContainText('Field team');
			await expect(rows.nth(1)).toContainText('Studio team');
			await expect(page.getByTestId('team-settings-team-avatar')).toHaveCount(2);
			await expect(page.getByTestId('team-create-open')).toBeVisible();
			await expect(
				page.getByText('No teams yet. Create one to collaborate securely.', { exact: true })
			).toHaveCount(0);
			await expectPhonePreviewFits(page);
		});
	});

	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,settings-ui.composition.canonical-and-accessible
	test('shows setup checklist and canonical overview navigation rows', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('detail'));
		await waitForComponentPreview(page);
		await test.step('overview: setup checklist and navigation rows fit the phone', async () => {
			await expect(page.getByTestId('team-settings-header')).toContainText('Studio team');
			const checklist = page.getByTestId('team-setup-checklist');
			await expect(checklist).toBeVisible();
			for (const label of ['Buy credits', 'Confirm security settings', 'Invite team members']) {
				await expect(checklist.getByRole('checkbox', { name: label })).toBeVisible();
			}
			for (const testId of [
				'team-billing-open',
				'team-members-open',
				'team-security-open',
				'team-name-open',
				'team-avatar-open',
				'team-delete-open'
			]) {
				await expect(page.getByTestId(testId)).toBeVisible();
			}
			await expect(page.getByTestId('team-checklist-dismiss')).toBeVisible();
			await expectPhonePreviewFits(page);
		});
		await page.getByTestId('team-checklist-dismiss').click();
		await expect(page.getByTestId('team-setup-checklist')).toHaveCount(0);
		await expect(page.getByTestId('team-members-open')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
	test('gates owner team deletion on explicit confirmation', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('delete'));
		await waitForComponentPreview(page);
		const confirmation = page.getByRole('checkbox', {
			name: 'I understand this team will be permanently deleted'
		});
		const submit = page.getByTestId('team-delete-submit');
		await test.step('deleteteam: warning and disabled destructive action fit the phone', async () => {
			await expect(
				page.getByText(
					'Team members will lose access to this team, its projects, and its shared data. This cannot be undone.'
				)
			).toBeVisible();
			await expect(confirmation).toBeVisible();
			await expect(submit).toBeDisabled();
			await expectPhonePreviewFits(page);
		});
		await confirmation.check();
		await expect(submit).toBeEnabled();
		await page.goto(preview('viewerDetail'));
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-delete-open')).toHaveCount(0);
		await expect(page.getByTestId('team-members-open')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,settings-ui.composition.canonical-and-accessible
	test('stages creation and shows a generated avatar preview on a phone', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('create'));
		await waitForComponentPreview(page);
		await test.step('newteam: name input and disabled Continue fit the phone', async () => {
			await expect(page.getByTestId('team-name-input')).toBeVisible();
			await expect(page.getByTestId('team-create-continue')).toBeDisabled();
			await expectPhonePreviewFits(page);
		});
		await expect(page.getByTestId('team-create-continue')).toBeDisabled();
		await page.getByTestId('team-name-input').fill('Studio team');
		await expect(page.getByTestId('team-create-continue')).toBeEnabled();
		let checkedName = '';
		await page.route('**/v1/teams/name-approval', async (route) => {
			checkedName = JSON.parse(route.request().postData() ?? '{}').name;
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ approval_token: 'preview-token' })
			});
		});
		await page.getByTestId('team-create-continue').click();
		await expect.poll(() => checkedName).toBe('studio team');
		await page.goto(preview('avatar'));
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-avatar-preview')).toBeVisible();
		await expect(page.getByTestId('team-avatar-icon')).toHaveCount(0);
		await expect(page.getByTestId('team-avatar-regenerate')).toHaveCSS('min-width', '0px');
		const regenerate = await page.getByTestId('team-avatar-regenerate').boundingBox();
		expect(regenerate?.width).toBe(40);
		expect(regenerate?.height).toBe(40);
		await expect(page.getByTestId('team-create-submit')).toHaveCSS(
			'background-color',
			'rgb(255, 85, 59)'
		);
		await expect(page.getByTestId('team-settings-header')).toBeVisible();
		const headerBox = await page.getByTestId('team-settings-header').boundingBox();
		expect(headerBox?.height).toBe(227);
		const avatarBox = await page.getByTestId('team-avatar-preview').boundingBox();
		expect(avatarBox?.width).toBe(144);
		expect(avatarBox?.height).toBe(144);
		await page.getByTestId('team-avatar-regenerate').click();
		await page.getByTestId('team-avatar-icon').selectOption('design');
		await page.getByTestId('team-avatar-color').selectOption('#8b62c9');
		await expect(page.getByTestId('team-avatar-preview')).toHaveCSS(
			'background-image',
			/linear-gradient\(135deg, rgb\(139, 98, 201\),/
		);
		await test.step('avatar: generated image and create controls fit the phone', async () => {
			await expect(page.getByTestId('team-avatar-preview')).toBeVisible();
			await expect(page.getByTestId('team-avatar-file')).toBeVisible();
			await expect(page.getByTestId('team-create-submit')).toBeVisible();
			await expectPhonePreviewFits(page);
			const avatar = await page.getByTestId('team-avatar-preview').boundingBox();
			const container = await page.getByTestId('teams-settings-page').boundingBox();
			expect(avatar).not.toBeNull();
			expect(container).not.toBeNull();
			expect(avatar!.x + avatar!.width / 2 - container!.x - container!.width / 2).toBeCloseTo(
				-7.5,
				0
			);
		});
	});

	// contract-test: direct surface=gui.web assertions=teams.profile-image.safe-parity,teams.lifecycle.encrypted-profiled
	test('preserves an uploaded profile image until the user explicitly changes it', async ({
		page
	}) => {
		await page.route('**/v1/teams/preview-team/profile-image', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'image/png',
				body: Buffer.from(
					'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aLasAAAAASUVORK5CYII=',
					'base64'
				)
			})
		);
		let profileWrites = 0;
		page.on('request', (request) => {
			if (
				request.method() === 'PATCH' &&
				/\/v1\/teams\/preview-team$/.test(new URL(request.url()).pathname)
			)
				profileWrites++;
		});
		await page.goto(preview('uploadedAvatar'));
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-avatar-preview').locator('img')).toBeVisible();
		await expect(page.getByTestId('team-avatar-save')).toBeDisabled();
		await expect(page.getByTestId('team-avatar-icon')).toHaveCount(0);
		expect(profileWrites).toBe(0);
		await test.step('uploadedavatar: current image is retained with Save disabled until an edit', async () => {
			await expectPhonePreviewFits(page);
		});
		await page.getByTestId('team-avatar-regenerate').click();
		await expect(page.getByTestId('team-avatar-preview').locator('img')).toHaveCount(0);
		await expect(page.getByTestId('team-avatar-save')).toBeEnabled();
		await expect(page.getByTestId('team-avatar-icon')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,teams.lifecycle.encrypted-profiled
	test('matches the default profile-image artboard composition', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('avatar'));
		await waitForComponentPreview(page);
		await expectPhonePreviewFits(page);
		await expect(page.getByTestId('team-avatar-icon')).toHaveCount(0);
		const frame = await page.locator('.teams-frame').boundingBox();
		const avatar = await page.getByTestId('team-avatar-preview').boundingBox();
		const upload = await page.getByTestId('team-avatar-file').boundingBox();
		const create = await page.getByTestId('team-create-submit').boundingBox();
		expect(frame).not.toBeNull();
		expect(avatar).not.toBeNull();
		expect(upload).not.toBeNull();
		expect(create).not.toBeNull();
		expect(avatar!.width).toBe(144);
		expect(avatar!.x - frame!.x).toBeCloseTo(82, 0);
		expect(avatar!.y - frame!.y).toBeCloseTo(249, 0);
		expect(upload!.y - frame!.y).toBeCloseTo(413, 0);
		expect(upload!.height).toBe(54);
		expect(create!.y - frame!.y).toBeCloseTo(487, 0);
		expect(create!.height).toBe(42);
		await expect(page.getByTestId('team-create-submit')).toHaveCSS(
			'background-color',
			'rgb(255, 85, 59)'
		);
		await expect(page.getByTestId('team-settings-header').locator('.app-name')).toHaveCSS(
			'color',
			'rgb(255, 255, 255)'
		);
	});

	// contract-test: direct surface=gui.web assertions=teams.name.transient-policy
	test('explains a blocked team name at the Continue step', async ({ page }) => {
		await page.goto(preview('create'));
		await waitForComponentPreview(page);
		await page.route('**/v1/teams/name-approval', (route) =>
			route.fulfill({
				status: 422,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'TEAM_NAME_BLOCKED' })
			})
		);
		await page.getByTestId('team-name-input').fill('Blocked name');
		await page.getByTestId('team-create-continue').click();
		await expect(page.getByTestId('team-action-error')).toContainText('Choose another team name');
		await expect(page.getByTestId('team-create-continue')).toBeEnabled();
	});

	// contract-test: direct surface=gui.web assertions=teams.security.join-policy,teams.invites.fragment-key-web-flow
	test('shows member and security states with inline domain guidance', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('members'));
		await waitForComponentPreview(page);
		await expect(page.getByText('Admins', { exact: true })).toBeVisible();
		await expectCanonicalMask(
			page
				.locator('.settings-section-heading')
				.filter({ hasText: 'Admins' })
				.locator('.heading-icon'),
			'safety',
			'::after'
		);
		await expectCanonicalMask(
			page
				.locator('.settings-section-heading')
				.filter({ hasText: 'Members' })
				.locator('.heading-icon'),
			'user',
			'::after'
		);
		await expect(page.getByTestId('team-member-row').filter({ hasText: 'Alex' })).toContainText(
			'member'
		);
		await expect(
			page.getByTestId('team-member-row').filter({ hasText: 'Alex' }).getByRole('button')
		).toBeVisible();
		await expect(page.getByTestId('team-member-detail-role')).toHaveCount(0);
		await expect(page.getByTestId('team-invite-email-input')).toBeVisible();
		await expect(page.getByTestId('team-invite-revoke-preview-invite')).toBeVisible();
		await expect(page.getByTestId('team-pending-invite-row')).toContainText(
			'Invite ready; awaiting acceptance'
		);
		await test.step('members: member controls and pending invite fit the phone', async () => {
			await expect(page.getByTestId('team-member-row')).toHaveCount(2);
			await expectPhonePreviewFits(page);
		});

		await page.goto(preview('security'));
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-security-domain-toggle')).toBeVisible();
		await expect(page.getByTestId('team-security-approval-toggle')).toBeVisible();
		await expect(page.getByTestId('team-security-strong-auth-toggle')).toBeVisible();
		await test.step('security: join controls fit the phone', async () => {
			await expectPhonePreviewFits(page);
		});
		let posted: Record<string, unknown> = {};
		await page.route('**/v1/teams/preview-team/security', async (route) => {
			posted = JSON.parse(route.request().postData() ?? '{}');
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ security_policy: posted })
			});
		});
		await page.getByTestId('team-security-domain-toggle').click();
		await expect.poll(() => posted.restrict_email_domains).toBe(true);
		await expect(page.getByTestId('team-security-domain-input')).toBeVisible();
		await page.getByTestId('team-security-domain-input').fill('example.org');
		await page.getByTestId('team-security-domain-add').click();
		await expect.poll(() => posted.allowed_email_domains).toEqual(['example.org']);
		await expect(page.getByTestId('team-security-domain-row')).toContainText('example.org');
		await expect(page.getByTestId('team-security-domain-add')).toHaveCount(0);
		await page.getByTestId('team-security-domain-remove-example.org').click();
		await expect.poll(() => posted.allowed_email_domains).toEqual([]);
	});

	// contract-test: direct surface=gui.web assertions=teams.membership.role-gated
	test('gates member removal on explicit confirmation in member detail', async ({ page }) => {
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(preview('memberDetail'));
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-member-detail')).toContainText('member');
		await expect(page.getByTestId('team-settings-header')).toContainText('Alex');
		await expect(page.getByTestId('team-member-detail-role')).toBeVisible();
		await test.step('memberdetail: identity and gated removal fit the phone', async () => {
			await expect(page.getByTestId('team-member-remove')).toBeDisabled();
			await expectPhonePreviewFits(page);
		});
		const remove = page.getByTestId('team-member-remove');
		await expect(remove).toBeDisabled();
		await page.getByRole('checkbox', { name: 'I understand this member will lose access' }).click();
		await expect(remove).toBeEnabled();
	});

	// contract-test: direct surface=gui.web assertions=teams.membership.role-gated
	test('lets non-admin members view encrypted identities without management controls', async ({
		page
	}) => {
		await page.goto(preview('viewerMembers'));
		await waitForComponentPreview(page);
		await expect(page.getByText('Alex', { exact: true })).toBeVisible();
		await expect(page.getByTestId('team-invite-email-input')).toHaveCount(0);
		await expect(page.getByTestId('team-member-role-member-preview')).toHaveCount(0);
		await page.goto(preview('viewerMemberDetail'));
		await waitForComponentPreview(page);
		await expect(page.getByText('Alex', { exact: true })).toBeVisible();
		await expect(page.getByTestId('team-member-remove')).toHaveCount(0);
	});

	// contract-test: direct surface=gui.web assertions=teams.security.join-policy
	test('shows the Security deep link immediately below a disallowed invite email', async ({
		page
	}) => {
		await page.goto(preview('restrictedMembers'));
		await waitForComponentPreview(page);
		await page.getByTestId('team-invite-email-input').fill('guest@other.example');
		await page.getByTestId('team-invite-submit').click();
		await expect(page.getByTestId('team-invite-inline-error')).toContainText('not allowed');
		await expect(
			page
				.getByTestId('team-invite-inline-error')
				.getByRole('link', { name: 'Change allowed domains in Security' })
		).toBeVisible();
	});
});
