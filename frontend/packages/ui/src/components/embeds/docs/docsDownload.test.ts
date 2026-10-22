import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchAndDecryptDocArtifact } from './docsArtifactCrypto';
import { prepareDocsDownload } from './docsDownload';
import { asBlob } from 'html-docx-js-typescript';
import { replaceEmbedRefsWithUrlsInHtml } from '../../../utils/embedLinkUtils';

vi.mock('./docsArtifactCrypto', () => ({ fetchAndDecryptDocArtifact: vi.fn() }));
vi.mock('html-docx-js-typescript', () => ({ asBlob: vi.fn() }));
vi.mock('../../../utils/embedLinkUtils', () => ({
  convertEmbedAnchorsToSpans: (value: string) => value,
  convertMarkdownEmbedLinksInHtml: (value: string) => value,
  convertMarkdownWikiLinksInHtml: (value: string) => value,
  convertWikiAnchorsToSpans: (value: string) => value,
  replaceEmbedRefsWithUrlsInHtml: vi.fn(async (value: string) => value.replace('embed:public-reference', 'https://example.test/reference')),
}));
vi.mock('../../enter_message/services/piiDetectionService', () => ({
  replacePIIOriginalsWithPlaceholders: (value: string, mappings: { original: string; placeholder: string }[]) => mappings.reduce((text, mapping) => text.split(mapping.original).join(mapping.placeholder), value),
  restorePIIInText: (value: string, mappings: { original: string; placeholder: string }[]) => mappings.reduce((text, mapping) => text.split(mapping.placeholder).join(mapping.original), value),
}));

const artifact = new Blob(['canonical-docx']);
const options = { filename: 'Report.DOCX', title: 'Report', htmlContent: '<p>Fallback</p>', docxS3Key: 'private/docx-key', aesKey: 'private-key' };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(asBlob).mockResolvedValue(artifact); });

describe('shared document downloads', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('prefers the canonical encrypted artifact and preserves the DOCX filename', async () => {
    vi.mocked(fetchAndDecryptDocArtifact).mockResolvedValue(artifact);
    expect(await prepareDocsDownload(options)).toEqual({ filename: 'Report.docx', blob: artifact });
    expect(fetchAndDecryptDocArtifact).toHaveBeenCalledWith('private/docx-key', 'private-key', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    expect(asBlob).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('reuses component-owned prepared URLs and in-flight decrypts', async () => {
    expect(await prepareDocsDownload({ ...options, preparedUrl: 'blob:prepared-docx' })).toEqual({ filename: 'Report.docx', url: 'blob:prepared-docx' });
    expect(await prepareDocsDownload({ ...options, preparedPromise: Promise.resolve(artifact) })).toEqual({ filename: 'Report.docx', blob: artifact });
    expect(fetchAndDecryptDocArtifact).not.toHaveBeenCalled();
    expect(asBlob).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('reports artifact decryption failure rather than silently replacing the canonical file', async () => {
    vi.mocked(fetchAndDecryptDocArtifact).mockRejectedValue(new Error('decrypt failed'));
    await expect(prepareDocsDownload(options)).rejects.toThrow('decrypt failed');
    expect(asBlob).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('sanitizes masked HTML and title, resolves embed references and keeps export formatting', async () => {
    const piiMappings = [{ original: 'alex@example.test', placeholder: '[EMAIL_1]', type: 'email' }];
    await prepareDocsDownload({ htmlContent: '<p onclick="unsafe()">alex@example.test embed:public-reference</p><script>unsafe()</script>', title: 'alex@example.test </title><script>unsafe()</script>', piiMappings });
    const [html, config] = vi.mocked(asBlob).mock.calls[0];
    expect(html).toContain('[EMAIL_1]');
    expect(html).not.toContain('alex@example.test');
    expect(html).not.toContain('onclick=');
    expect(html).not.toContain('<script>');
    expect(html).toContain('https://example.test/reference');
    expect(html).toContain('&lt;/title&gt;');
    expect(html).toContain('font-family: Calibri, Arial, sans-serif');
    expect(config).toEqual({ margins: { top: 1440, right: 1440, bottom: 1440, left: 1440 } });
    expect(replaceEmbedRefsWithUrlsInHtml).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('uses the owner reveal setting when generating fallback HTML', async () => {
    await prepareDocsDownload({ htmlContent: '<p>[EMAIL_1]</p>', piiRevealed: true, piiMappings: [{ original: 'alex@example.test', placeholder: '[EMAIL_1]', type: 'email' }] });
    expect(vi.mocked(asBlob).mock.calls[0][0]).toContain('alex@example.test');
  });
});
