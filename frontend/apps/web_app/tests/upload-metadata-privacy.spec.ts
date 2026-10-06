/* eslint-disable @typescript-eslint/no-require-imports */
export {};

// contract-test: supporting surface=gui.web,cli assertions=pii.surface.semantic-parity,cli.surface.semantic-parity
// Capture the actual multipart requests made by the composer and CLI/TUI upload transports.
// The payload markers are embedded in valid file metadata, never in visible content.

import { execFile } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { deflateSync } from 'node:zlib';
import type { Page, Route } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const execFileAsync = promisify(execFile);
const fixtureDirectory = join(__dirname, 'fixtures');
const marker = 'PRIVATE_UPLOAD_METADATA_70B4';
const uploadResponse = {
  embed_id: '00000000-0000-4000-8000-000000000001', filename: 'private-person.png',
  content_type: 'image/png', content_hash: 'test-content-hash',
  files: { original: { s3_key: 'test-object', width: 1, height: 1, size_bytes: 1, format: 'png' } },
  s3_base_url: 'https://example.invalid', aes_key: 'test-key', aes_nonce: 'test-nonce',
  vault_wrapped_aes_key: 'test-wrapped-key', malware_scan: 'clean', ai_detection: null,
  deduplicated: true, page_count: 1,
};

function crc32(bytes: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngWithTextMetadata(): Buffer {
  const chunk = (type: string, data: Buffer): Buffer => {
    const typeAndData = Buffer.concat([Buffer.from(type), data]);
    const bytes = Buffer.alloc(8 + typeAndData.length);
    bytes.writeUInt32BE(data.length, 0);
    typeAndData.copy(bytes, 4);
    bytes.writeUInt32BE(crc32(typeAndData), bytes.length - 4);
    return bytes;
  };
  const ihdr = Buffer.from([0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0]);
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('tEXt', Buffer.from(`Author\0${marker}`)),
    chunk('IDAT', deflateSync(Buffer.from([0, 0, 0, 0, 255]))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function jpegWithXmpMetadata(): Buffer {
  const original = readFileSync(join(fixtureDirectory, 'finance.jpeg'));
  const payload = Buffer.from(`http://ns.adobe.com/xap/1.0/\0${marker}`);
  const app1 = Buffer.alloc(payload.length + 4);
  app1[0] = 0xff;
  app1[1] = 0xe1;
  app1.writeUInt16BE(payload.length + 2, 2);
  payload.copy(app1, 4);
  return Buffer.concat([original.subarray(0, 2), app1, original.subarray(2)]);
}

function pdfWithInfoAndXmpMetadata(): Buffer {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R /Metadata 5 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>',
    '<< /Length 0 >>\nstream\n\nendstream',
    (() => { const xml = `<x:xmpmeta xmlns:x="adobe:ns:meta/">${marker}</x:xmpmeta>`;
      return `<< /Type /Metadata /Subtype /XML /Length ${Buffer.byteLength(xml)} >>\nstream\n${xml}\nendstream`; })(),
    `<< /Author (${marker}) /Creator (OpenMates test) >>`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) pdf += `${String(offset).padStart(10, '0')} 00000 n \n`;
  pdf += `trailer\n<< /Size ${offsets.length} /Root 1 0 R /Info 6 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf);
}

function wavWithListMetadata(): Buffer {
  const value = Buffer.from(`${marker}\0`);
  const header = Buffer.alloc(8);
  header.write('INAM', 0);
  header.writeUInt32LE(value.length, 4);
  const info = Buffer.concat([header, value, value.length & 1 ? Buffer.alloc(1) : Buffer.alloc(0)]);
  const list = Buffer.concat([Buffer.from('LIST'), Buffer.alloc(4), Buffer.from('INFO'), info]);
  list.writeUInt32LE(list.length - 8, 4);
  const fmt = Buffer.from([0x66, 0x6d, 0x74, 0x20, 16, 0, 0, 0, 1, 0, 1, 0, 0x40, 0x1f, 0, 0, 0x80, 0x3e, 0, 0, 2, 0, 16, 0]);
  const data = Buffer.from([0x64, 0x61, 0x74, 0x61, 2, 0, 0, 0, 0, 0]);
  const wav = Buffer.concat([Buffer.from('RIFF'), Buffer.alloc(4), Buffer.from('WAVE'), fmt, list, data]);
  wav.writeUInt32LE(wav.length - 8, 4);
  return wav;
}

async function captureUpload(page: Page, endpoint: string, responseJson: object = uploadResponse): Promise<Buffer[]> {
  const payloads: Buffer[] = [];
  await page.route(`**${endpoint}`, async (route: Route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const payload = route.request().postDataBuffer();
    if (payload) payloads.push(payload);
    const filename = payload?.toString().match(/filename="([^"]+)"/)?.[1];
    const body = 'filename' in responseJson && filename ? { ...responseJson, filename } : responseJson;
    const origin = new URL(page.url()).origin;
    await route.fulfill({ status: 200, contentType: 'application/json',
      headers: { 'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true' },
      json: body });
  });
  return payloads;
}

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('composer keeps filenames, strips image and PDF metadata, and still sends malformed images', async ({ page }: { page: Page }) => {
  test.setTimeout(120000);
  const { email, password, otpKey } = getTestAccount();
  skipWithoutCredentials(test, email, password, otpKey);
  const payloads = await captureUpload(page, '/v1/upload/file');
  await page.goto(getE2EDebugUrl('/'));
  await loginToTestAccount(page);
  await expect(page.getByTestId('message-editor')).toBeVisible();

  const files = [
    { name: 'private-person.png', mimeType: 'image/png', buffer: pngWithTextMetadata(), expectClean: true },
    { name: 'private-person.pdf', mimeType: 'application/pdf', buffer: pdfWithInfoAndXmpMetadata(), expectClean: true },
    { name: 'broken-private.png', mimeType: 'image/png', buffer: Buffer.from(`broken png ${marker}`), expectClean: false },
  ];
  for (const file of files) {
    expect(file.buffer.includes(marker)).toBe(true);
    const expectedCount = payloads.length + 1;
    await page.getByTestId('message-file-input').setInputFiles(file);
    await expect.poll(() => payloads.length, { timeout: 20000 }).toBe(expectedCount);
    const sent = payloads.at(-1)!;
    expect(sent.includes(`filename="${file.name}"`)).toBe(true);
    expect(sent.includes(marker)).toBe(!file.expectClean);
    if (file.expectClean) expect(sent.includes(file.buffer)).toBe(false);
  }
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('profile picture upload keeps its generated filename without source XMP', async ({ page }: { page: Page }) => {
  test.setTimeout(120000);
  const { email, password, otpKey } = getTestAccount();
  skipWithoutCredentials(test, email, password, otpKey);
  const payloads = await captureUpload(page, '/v1/upload/profile-image', {
    status: 'ok', url: 'https://example.invalid/test-avatar.png',
  });
  await page.goto(getE2EDebugUrl('/'));
  await loginToTestAccount(page);
  await page.getByTestId('profile-container').click();
  await expect(page.getByTestId('settings-menu')).toBeVisible();
  await page.getByRole('button', { name: /^profile picture$/i }).click();
  const source = jpegWithXmpMetadata();
  expect(source.includes(marker)).toBe(true);
  await page.locator('.profile-picture-container input[type="file"]').setInputFiles({
    name: 'private-portrait.jpg', mimeType: 'image/jpeg', buffer: source,
  });
  await expect.poll(() => payloads.length, { timeout: 20000 }).toBe(1);
  expect(payloads[0].includes(marker)).toBe(false);
  expect(payloads[0].includes('filename="private-portrait.jpg"')).toBe(true);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,pii.surface.semantic-parity
test('CLI and TUI keep names, strip multipart metadata, and keep failed cleanup best effort', async () => {
  test.setTimeout(60000);
  const directory = mkdtempSync(join(tmpdir(), 'upload-metadata-e2e-'));
  try {
    writeFileSync(join(directory, 'private-person.png'), pngWithTextMetadata());
    writeFileSync(join(directory, 'private-person.pdf'), pdfWithInfoAndXmpMetadata());
    writeFileSync(join(directory, 'private-person.wav'), wavWithListMetadata());
    writeFileSync(join(directory, 'broken-private.png'), `broken png ${marker}`);
    const helper = join(__dirname, 'upload-metadata-privacy-probe.mjs');
    const loader = join(__dirname, '../../../packages/openmates-cli/tests/loader.mjs');
    const { stdout } = await execFileAsync(process.execPath,
      ['--experimental-strip-types', '--loader', loader, helper, directory, marker],
      { timeout: 45000, maxBuffer: 1024 * 1024 });
    expect(stdout).toContain('CLI/TUI multipart privacy probe passed');
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
