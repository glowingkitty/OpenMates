/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Office import E2E: a multi-sheet XLSX becomes one sheet embed per worksheet
 * with its supported formulas kept and calculated, features the sheet embed
 * cannot represent (here: a chart) are reported to the user, and PowerPoint
 * files show a "slides support is coming soon" notice instead of failing
 * silently. Nothing is sent, so no model credentials are needed.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

/** Minimal stored (uncompressed) ZIP writer: avoids a jszip dependency the web_app test package does not resolve. */
function crc32(data: Buffer): number {
	let crc = 0xffffffff;
	for (const byte of data) {
		crc ^= byte;
		for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
	}
	return (crc ^ 0xffffffff) >>> 0;
}

function createStoredZip(files: Record<string, string>): Buffer {
	const locals: Buffer[] = [];
	const centrals: Buffer[] = [];
	let offset = 0;
	for (const [name, content] of Object.entries(files)) {
		const nameBuf = Buffer.from(name);
		const data = Buffer.from(content);
		const crc = crc32(data);
		const local = Buffer.alloc(30);
		local.writeUInt32LE(0x04034b50, 0);
		local.writeUInt16LE(20, 4);
		local.writeUInt32LE(crc, 14);
		local.writeUInt32LE(data.length, 18);
		local.writeUInt32LE(data.length, 22);
		local.writeUInt16LE(nameBuf.length, 26);
		const central = Buffer.alloc(46);
		central.writeUInt32LE(0x02014b50, 0);
		central.writeUInt16LE(20, 4);
		central.writeUInt16LE(20, 6);
		central.writeUInt32LE(crc, 16);
		central.writeUInt32LE(data.length, 20);
		central.writeUInt32LE(data.length, 24);
		central.writeUInt16LE(nameBuf.length, 28);
		central.writeUInt32LE(offset, 42);
		locals.push(local, nameBuf, data);
		centrals.push(central, nameBuf);
		offset += local.length + nameBuf.length + data.length;
	}
	const centralBuf = Buffer.concat(centrals);
	const end = Buffer.alloc(22);
	end.writeUInt32LE(0x06054b50, 0);
	end.writeUInt16LE(Object.keys(files).length, 8);
	end.writeUInt16LE(Object.keys(files).length, 10);
	end.writeUInt32LE(centralBuf.length, 12);
	end.writeUInt32LE(offset, 16);
	return Buffer.concat([...locals, centralBuf, end]);
}

function createFormulaWorkbookBuffer(): Buffer {
  const ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"';
  return createStoredZip({
    'xl/workbook.xml': `<workbook ${ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/><sheet name="Notes" sheetId="2" r:id="rId2"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="worksheet" Target="worksheets/sheet2.xml"/></Relationships>',
    'xl/worksheets/sheet1.xml': `<worksheet ${ns}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Base</t></is></c><c r="B1" t="inlineStr"><is><t>Doubled</t></is></c></row><row r="2"><c r="A2"><v>21</v></c><c r="B2"><f>A2*2</f><v>42</v></c></row></sheetData></worksheet>`,
    'xl/worksheets/sheet2.xml': `<worksheet ${ns}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Topic</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Second sheet note</t></is></c></row></sheetData></worksheet>`,
    'xl/charts/chart1.xml': '<chartSpace/>'
  });
}

// contract-test: direct surface=gui.web assertions=message-input.embeds.gated-send
test('multi-sheet XLSX keeps formulas per sheet and PowerPoint shows a coming-soon notice', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FILE_ATTACH_OFFICE_NOTICES');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-office-notices' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await startNewChat(page, log);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 10000 });
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });
	await fileInput.setInputFiles(
		[
			{
				name: 'budget.xlsx',
				mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
				buffer: createFormulaWorkbookBuffer()
			},
			{
				name: 'deck.pptx',
				mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
				buffer: Buffer.from('PK')
			}
		]
	);

	const sheetEmbeds = page.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]');
	await expect(sheetEmbeds).toHaveCount(2, { timeout: 20000 });
	await expect(
		page.getByTestId('notification').filter({ hasText: /slides support is coming soon/i })
	).toBeVisible({ timeout: 10000 });
	await expect(
		page.getByTestId('notification').filter({ hasText: /Excel features aren't supported/i })
	).toBeVisible({ timeout: 10000 });
	await screenshot(page, 'office-notices');

	const firstSheet = sheetEmbeds.first();
	await expect(firstSheet).toContainText('Doubled', { timeout: 10000 });
	await expect(firstSheet).toContainText('42', { timeout: 10000 });
	await expect(firstSheet.locator('td[data-formula]')).toHaveAttribute('data-formula', '=A1*2', {
		timeout: 10000
	});
	await expect(sheetEmbeds.nth(1)).toContainText('Second sheet note', { timeout: 10000 });
	log('Multi-sheet XLSX produced two sheet embeds with a calculated formula; PPTX showed the notice.');
});
