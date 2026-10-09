import { describe, expect, it } from 'vitest';
import { publicExamplePdfPageImageUrl, publicExamplePdfUrl } from './publicExamplePdf';

describe('reviewed public PDF path', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('accepts only the exact same-origin example and its generated page image', () => {
    const pdf = '/store-examples/community-garden-budget.pdf';
    expect(publicExamplePdfUrl(pdf)).toBe(pdf);
    expect(publicExamplePdfPageImageUrl(pdf)).toBe('/store-examples/community-garden-budget-page-1.png');
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it.each([
    '/store-examples/community-garden-budget.pdf?download=1',
    '/store-examples/../private.pdf',
    '/store-examples/other.pdf',
    'https://example.com/community-garden-budget.pdf',
    '//example.com/community-garden-budget.pdf',
    'javascript:alert(1)',
  ])('rejects unreviewed path %s', (path) => {
    expect(publicExamplePdfUrl(path)).toBeUndefined();
    expect(publicExamplePdfPageImageUrl(path)).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('rejects the public path when encrypted credentials are present', () => {
    expect(publicExamplePdfUrl('/store-examples/community-garden-budget.pdf', true)).toBeUndefined();
    expect(publicExamplePdfPageImageUrl('/store-examples/community-garden-budget.pdf', true)).toBeUndefined();
  });
});
