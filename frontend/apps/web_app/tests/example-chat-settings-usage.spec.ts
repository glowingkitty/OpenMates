/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chat settings usage regression tests.
 *
 * Verifies that guest-accessible static example chats can show real historical
 * usage costs when the generated example data includes static usage_entries.
 * The flow stays unauthenticated and must not depend on private usage APIs.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const fs = require('fs');
const JSZip = require('jszip');

const GENERATED_AUDIO_USAGE_CASES = [
  {
    chatId: 'example-community-garden-volunteer-chime',
    totalCredits: /83\s*credits/i,
    aiCredits: '43',
    audioLabel: 'audio | generate',
    audioCredits: '40',
    filename: 'community-garden-volunteer-chime.mp3'
  }
] as const;

const STATIC_FILE_CASES = [
	{
		chatId: 'example-screenshot-to-html-pricing',
		filename: 'index.html',
		metadata: 'Code file',
    usage: true
	},
	{
		chatId: 'example-community-garden-volunteer-onboarding',
		filename: 'Volunteer_Onboarding_Guide.docx',
		metadata: 'Document',
    usage: false
	}
] as const;

async function openExampleSettings(
	page: any,
	exampleChatId: string,
	options: { expectFilesTab?: boolean; expectUsageTab?: boolean } = {}
): Promise<any> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), {
		waitUntil: 'domcontentloaded'
	});

	await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('chat-details-button')).toBeVisible({ timeout: 10000 });

	await page.getByTestId('chat-details-button').click();
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', `chats/${exampleChatId}`, {
		timeout: 10000
	});
	await expect(settingsMenu.getByTestId('chat-settings-tab-share')).toBeVisible({ timeout: 10000 });
	if (options.expectUsageTab === false) {
		await expect(settingsMenu.getByTestId('chat-settings-tab-usage')).toHaveCount(0);
	} else {
		await expect(settingsMenu.getByTestId('chat-settings-tab-usage')).toBeVisible({ timeout: 10000 });
	}
	await expect(settingsMenu.getByTestId('chat-settings-tab-plan')).toHaveCount(0);
	await expect(settingsMenu.getByTestId('chat-settings-tab-tasks')).toHaveCount(0);
	if (options.expectFilesTab) {
		await expect(settingsMenu.getByTestId('chat-settings-tab-files')).toBeVisible({ timeout: 10000 });
	} else {
		await expect(settingsMenu.getByTestId('chat-settings-tab-files')).toHaveCount(0);
	}

	return settingsMenu;
}

async function openExampleUsageTab(
	page: any,
	exampleChatId: string,
	options: { expectFilesTab?: boolean } = {}
): Promise<any> {
	const settingsMenu = await openExampleSettings(page, exampleChatId, options);

	await settingsMenu.getByTestId('chat-settings-tab-usage').click();
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-usage')).toBeVisible({ timeout: 10000 });
	return settingsMenu;
}

async function readZipEntryNames(download: any, outputPath: string): Promise<string[]> {
	await download.saveAs(outputPath);
	const zip = await JSZip.loadAsync(fs.readFileSync(outputPath));
	return Object.keys(zip.files);
}

test.describe('Example chat settings usage', () => {
	// contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,public-example-chats.surface.semantic-parity
	test('guest example chat with static usage exposes usage tab and rows', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		const exampleChatId = 'example-private-plumber-email';

		const settingsMenu = await openExampleUsageTab(page, exampleChatId);
		await expect(settingsMenu.getByTestId('chat-settings-usage-total')).toContainText(/14\s*credits/i);
		const rows = settingsMenu.getByTestId('chat-settings-usage-row');
		await expect(rows).toHaveCount(1);
		await expect(rows.first()).toContainText('ai | ask');
		await expect(rows.first()).toContainText('Google AI Studio / US');
		await expect(rows.first()).toContainText('14');
	});

	// contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,audio-generate.billing.success-only
	test('generated audio example chats include audio app-skill usage rows', async ({ page }: { page: any }) => {
		test.setTimeout(90000);

		for (const exampleCase of GENERATED_AUDIO_USAGE_CASES) {
			const settingsMenu = await openExampleUsageTab(page, exampleCase.chatId, {
				expectFilesTab: true
			});
			const rows = settingsMenu.getByTestId('chat-settings-usage-row');
      const aiRow = rows.filter({ hasText: 'ai | ask' });
      const audioRow = rows.filter({ hasText: exampleCase.audioLabel });
			await expect(settingsMenu.getByTestId('chat-settings-usage-total')).toContainText(exampleCase.totalCredits);
			await expect(rows).toHaveCount(2);
			await expect(aiRow).toContainText('ai | ask');
			await expect(aiRow).toContainText('Google AI Studio / US');
			await expect(aiRow).toContainText(exampleCase.aiCredits);
			await expect(audioRow).toContainText(exampleCase.audioLabel);
			await expect(audioRow).toContainText('ElevenLabs / US');
			await expect(audioRow).toContainText(exampleCase.audioCredits);
		}
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.surface.semantic-parity
	test('static example chats expose code and document files in settings', async ({ page }: { page: any }) => {
		test.setTimeout(120000);

		for (const exampleCase of STATIC_FILE_CASES) {
			const settingsMenu = await openExampleSettings(page, exampleCase.chatId, {
				expectFilesTab: true,
				expectUsageTab: exampleCase.usage
			});

			await settingsMenu.getByTestId('chat-settings-tab-files').click();
			const filesPanel = settingsMenu.getByTestId('chat-settings-tabpanel-files');
			await expect(filesPanel).toBeVisible({ timeout: 10000 });
			await expect(filesPanel.getByTestId('chat-settings-file-row').filter({ hasText: exampleCase.filename })).toBeVisible({ timeout: 10000 });
			await expect(filesPanel.getByTestId('chat-settings-file-row').filter({ hasText: exampleCase.filename })).toContainText(exampleCase.metadata);
			await expect(filesPanel.getByTestId('chat-settings-download-files')).toContainText(/downloadable item/i);
		}
	});

	// contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,public-example-chats.surface.semantic-parity
	test('example chat cost label deep links to usage details', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		const exampleChatId = 'example-community-garden-volunteer-chime';

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
		const costLink = page.getByTestId('generated-by-cost').first();
		await expect(costLink).toContainText(/83\s*credits/i, { timeout: 10000 });
		await costLink.click();

		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu).toHaveAttribute('data-active-view', `chats/${exampleChatId}/usage`, {
			timeout: 10000
		});
		await expect(settingsMenu.getByTestId('chat-settings-tabpanel-usage')).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu.getByTestId('chat-settings-usage-total')).toContainText(/83\s*credits/i);
		await expect(settingsMenu.getByTestId('chat-settings-usage-row')).toHaveCount(2);
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.surface.semantic-parity,audio-generate.output.playable-audio,audio-generate.surface-parity
	test('generated audio example chats expose static MP3 files in settings and ZIP exports', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(120000);

		for (const exampleCase of GENERATED_AUDIO_USAGE_CASES) {
			const settingsMenu = await openExampleSettings(page, exampleCase.chatId, {
				expectFilesTab: true
			});

			await settingsMenu.getByTestId('chat-settings-tab-files').click();
			const filesPanel = settingsMenu.getByTestId('chat-settings-tabpanel-files');
			await expect(filesPanel).toBeVisible({ timeout: 10000 });
			const fileRows = filesPanel.getByTestId('chat-settings-file-row');
			await expect(fileRows).toHaveCount(1);
			await expect(fileRows.first()).toContainText(exampleCase.filename);
			await expect(fileRows.first()).toContainText('Audio');
			await expect(filesPanel.getByTestId('chat-settings-download-files')).toContainText('1 downloadable item');

			const downloadPromise = page.waitForEvent('download', { timeout: 45000 });
			await filesPanel.getByTestId('chat-settings-download-files').click();
			const download = await downloadPromise;
			expect(download.suggestedFilename()).toMatch(/\.zip$/);
			const zipEntries = await readZipEntryNames(
				download,
				testInfo.outputPath(`${exampleCase.chatId}.zip`)
			);
			expect(zipEntries).toContain(`generated-audio/${exampleCase.filename}`);
		}
	});
});
